"""
텍스트 검출 네트워크 — Backbone + U-Net 디코더.

- Backbone에서 다단계 특징맵 추출 → U-Net 디코더로 업샘플/결합
- 최종 출력: region score map + affinity score map (2채널)
- Backbone 옵션: VGG11/16/19_BN, MobileNetV3 Small/Large

사용 예시::

    model = build_detector("MOBILENET_V3_LARGE", pretrained=False)
    y, feature = model(x)
"""
from __future__ import annotations

from collections import namedtuple
from collections.abc import Iterable
from typing import Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models

import logging

logger = logging.getLogger("detector_arch")

# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

BackboneOutputs = namedtuple(
    "BackboneOutputs",
    ["fc7", "relu5_3", "relu4_3", "relu3_2", "relu2_2"],
)


def init_weights(modules: Iterable[nn.Module]) -> None:
    """Xavier 가중치 초기화"""
    for m in modules:
        if isinstance(m, nn.Conv2d):
            nn.init.xavier_uniform_(m.weight.data)
            if m.bias is not None:
                m.bias.data.zero_()
        elif isinstance(m, nn.BatchNorm2d):
            m.weight.data.fill_(1)
            m.bias.data.zero_()


class DoubleConv(nn.Module):
    """Conv-BN-ReLU × 2 블록 (VGG DetNet용, in_ch+mid_ch 입력)"""

    def __init__(self, in_ch: int, mid_ch: int, out_ch: int) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch + mid_ch, mid_ch, kernel_size=1),
            nn.BatchNorm2d(mid_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(mid_ch, out_ch, kernel_size=3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv(x)


class DoubleConvMobile(nn.Module):
    """1×1 → 3×3 블록 (MobileDetNet용, in_channels 직접 입력)"""

    def __init__(self, in_channels: int, mid_channels: int, out_channels: int) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_channels, mid_channels, kernel_size=1, bias=False),
            nn.BatchNorm2d(mid_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(mid_channels, out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode="fan_out", nonlinearity="relu")
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv(x)


class SEBlock(nn.Module):
    """Squeeze-and-Excitation 블록"""

    def __init__(self, channels: int, reduction: int = 4) -> None:
        super().__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.fc = nn.Sequential(
            nn.Linear(channels, channels // reduction, bias=False),
            nn.ReLU(inplace=True),
            nn.Linear(channels // reduction, channels, bias=False),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, c, _, _ = x.size()
        y = self.avg_pool(x).view(b, c)
        y = self.fc(y).view(b, c, 1, 1)
        return x * y.expand_as(x)


# ===================================================================
# VGG Backbone + DetNet
# ===================================================================

class VGGBackbone(nn.Module):
    """
    VGG + BatchNorm backbone (vgg11, vgg16, vgg19)

    기존 VGG16_BN 클래스와 동일한 state_dict 키 구조 유지:
    - slice1~4: add_module(str(original_index)) 방식
    - slice5: MaxPool + Conv + Conv (ReLU 없음)

    출력: BackboneOutputs(fc7=1024, relu5_3=512, relu4_3=512, relu3_2=256, relu2_2=128)
    """

    VGG_MODELS = {
        "vgg11": (models.vgg11_bn, [6, 4, 7, 7]),
        "vgg16": (models.vgg16_bn, [12, 7, 10, 10]),
        "vgg19": (models.vgg19_bn, [12, 10, 13, 13]),
    }

    def __init__(
        self,
        vgg_type: str = "vgg16",
        pretrained: bool = True,
        freeze: bool = False,
        pretrained_weight_path: Optional[str] = None,
    ) -> None:
        super().__init__()

        model_fn, layer_counts = self.VGG_MODELS[vgg_type]

        vgg = model_fn(weights=None)
        if pretrained and pretrained_weight_path:
            state_dict = torch.load(
                pretrained_weight_path, map_location="cpu", weights_only=True,
            )
            vgg.load_state_dict(state_dict)

        features = vgg.features
        c1, c2, c3, c4 = layer_counts

        # 기존 VGG16_BN과 동일한 키 구조: add_module(str(원본_인덱스))
        self.slice1 = nn.Sequential()
        self.slice2 = nn.Sequential()
        self.slice3 = nn.Sequential()
        self.slice4 = nn.Sequential()

        idx = 0
        for x in range(idx, idx + c1):
            self.slice1.add_module(str(x), features[x])
        idx += c1
        for x in range(idx, idx + c2):
            self.slice2.add_module(str(x), features[x])
        idx += c2
        for x in range(idx, idx + c3):
            self.slice3.add_module(str(x), features[x])
        idx += c3
        for x in range(idx, idx + c4):
            self.slice4.add_module(str(x), features[x])

        # fc6, fc7 — 기존 구조와 동일 (ReLU 없음)
        self.slice5 = nn.Sequential(
            nn.MaxPool2d(kernel_size=3, stride=1, padding=1),
            nn.Conv2d(512, 1024, kernel_size=3, padding=6, dilation=6),
            nn.Conv2d(1024, 1024, kernel_size=1),
        )

        if not pretrained:
            init_weights(self.slice1.modules())
            init_weights(self.slice2.modules())
            init_weights(self.slice3.modules())
            init_weights(self.slice4.modules())
        init_weights(self.slice5.modules())

        if freeze:
            for param in self.slice1.parameters():
                param.requires_grad = False

    def forward(self, x: torch.Tensor) -> BackboneOutputs:
        # slice1: relu2_2 — 세밀한 엣지/텍스처 (128ch, 1/2 해상도)
        h = self.slice1(x)
        h_relu2_2 = h
        # slice2: relu3_2 — 중간 해상도 특징맵 (256ch, 1/4 해상도)
        h = self.slice2(h)
        h_relu3_2 = h
        # slice3: relu4_3 — 고수준 의미론적 특징맵 (512ch, 1/8 해상도)
        h = self.slice3(h)
        h_relu4_3 = h
        # slice4: relu5_3 — 깊은 의미론적 특징맵 (512ch, 1/16 해상도)
        h = self.slice4(h)
        h_relu5_3 = h
        # slice5: fc6+fc7 atrous conv → 1024ch 최상위 특징맵 (stride 유지)
        h = self.slice5(h)
        h_fc7 = h
        return BackboneOutputs(h_fc7, h_relu5_3, h_relu4_3, h_relu3_2, h_relu2_2)


class DetNet(nn.Module):
    """
    VGG backbone DetNet 모델

    기존 구현과 동일한 state_dict 키 구조:
    - basenet: VGGBackbone
    - upconv1~4: DoubleConv
    - conv_cls: classification head
    """

    def __init__(
        self,
        backbone_type: str = "vgg16",
        pretrained: bool = True,
        freeze: bool = False,
        pretrained_weight_path: Optional[str] = None,
        **kwargs: object,
    ) -> None:
        super().__init__()

        # 'basenet' 이름 유지 — 기존 state_dict 호환
        self.basenet = VGGBackbone(
            backbone_type, pretrained, freeze, pretrained_weight_path,
        )

        self.upconv1 = DoubleConv(1024, 512, 256)
        self.upconv2 = DoubleConv(512, 256, 128)
        self.upconv3 = DoubleConv(256, 128, 64)
        self.upconv4 = DoubleConv(128, 64, 32)

        num_class = 2
        self.conv_cls = nn.Sequential(
            nn.Conv2d(32, 32, kernel_size=3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(32, 32, kernel_size=3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(32, 16, kernel_size=3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(16, 16, kernel_size=1), nn.ReLU(inplace=True),
            nn.Conv2d(16, num_class, kernel_size=1),
        )

        init_weights(self.upconv1.modules())
        init_weights(self.upconv2.modules())
        init_weights(self.upconv3.modules())
        init_weights(self.upconv4.modules())
        init_weights(self.conv_cls.modules())

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Returns:
            (y, feature)
            - y: score map (B, H, W, 2) — 채널 0=score_text, 1=score_link
            - feature: 디코더 마지막 특징맵 (B, 32, H, W)
        """
        # VGG backbone에서 다단계 특징맵 추출
        sources = self.basenet(x)

        # U-Net 디코더: fc7 + relu5_3 concat → upconv1
        y = torch.cat([sources[0], sources[1]], dim=1)
        y = self.upconv1(y)

        # relu4_3 해상도로 업샘플 후 스킵 연결
        y = F.interpolate(y, size=sources[2].size()[2:],
                          mode="bilinear", align_corners=False)
        y = torch.cat([y, sources[2]], dim=1)
        y = self.upconv2(y)

        # relu3_2 해상도로 업샘플 후 스킵 연결
        y = F.interpolate(y, size=sources[3].size()[2:],
                          mode="bilinear", align_corners=False)
        y = torch.cat([y, sources[3]], dim=1)
        y = self.upconv3(y)

        # relu2_2 해상도로 업샘플 후 스킵 연결 → 최종 feature map
        y = F.interpolate(y, size=sources[4].size()[2:],
                          mode="bilinear", align_corners=False)
        y = torch.cat([y, sources[4]], dim=1)
        feature = self.upconv4(y)

        # 분류 헤드: (B, 2, H, W) → permute → (B, H, W, 2)
        y = self.conv_cls(feature)
        return y.permute(0, 2, 3, 1), feature


# ===================================================================
# BaseDetNet — 공통 U-Net 디코더 (MobileDetNet용)
# ===================================================================

class BaseDetNet(nn.Module):
    """
    DetNet 공통 U-Net 디코더

    서브클래스에서 backbone, upconv1-4를 설정하고
    _initialize_classifier()를 호출해야 합니다.
    """

    def __init__(self) -> None:
        super().__init__()
        self.backbone = None
        self.upconv1 = None
        self.upconv2 = None
        self.upconv3 = None
        self.upconv4 = None
        self.conv_cls = None

    def _initialize_classifier(self, in_channels: int = 32) -> None:
        """분류 헤드 초기화"""
        self.conv_cls = nn.Sequential(
            nn.Conv2d(in_channels, in_channels, 3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(in_channels, in_channels, 3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(in_channels, in_channels // 2, 3, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(in_channels // 2, in_channels // 2, 1),
            nn.ReLU(inplace=True),
            nn.Conv2d(in_channels // 2, 2, 1),
        )

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Returns:
            (y, feature)
            - y: score map (B, H, W, 2) — 채널 0=score_text, 1=score_link
            - feature: 디코더 마지막 특징맵 (B, 32, H, W)
        """
        # MobileNet/기타 backbone에서 다단계 특징맵 추출
        sources = self.backbone(x)

        # U-Net 디코더: fc7 + relu5_3 concat → upconv1
        y = torch.cat([sources.fc7, sources.relu5_3], dim=1)
        y = self.upconv1(y)

        # relu4_3 해상도로 업샘플 후 스킵 연결
        y = F.interpolate(y, size=sources.relu4_3.size()[2:],
                          mode="bilinear", align_corners=False)
        y = torch.cat([y, sources.relu4_3], dim=1)
        y = self.upconv2(y)

        # relu3_2 해상도로 업샘플 후 스킵 연결
        y = F.interpolate(y, size=sources.relu3_2.size()[2:],
                          mode="bilinear", align_corners=False)
        y = torch.cat([y, sources.relu3_2], dim=1)
        y = self.upconv3(y)

        # relu2_2 해상도로 업샘플 후 스킵 연결 → 최종 feature map
        y = F.interpolate(y, size=sources.relu2_2.size()[2:],
                          mode="bilinear", align_corners=False)
        y = torch.cat([y, sources.relu2_2], dim=1)
        feature = self.upconv4(y)

        # 분류 헤드: (B, 2, H, W) → permute → (B, H, W, 2)
        y = self.conv_cls(feature)
        return y.permute(0, 2, 3, 1), feature


# ===================================================================
# MobileNet V3 Backbone + MobileDetNet (adaptor 방식)
# ===================================================================

class MobileBackbone(nn.Module):
    """
    MobileNetV3 backbone (Small/Large) — adaptor로 채널 수 통일

    출력: BackboneOutputs(fc7=1024, relu5_3=512, relu4_3=256, relu3_2=128, relu2_2=64)
    """

    MODEL_CONFIGS = {
        "mobile_v3_small": {
            "model": models.mobilenet_v3_small,
            "input_scale": 1.5,
            "stages": [
                {"layers": (0, 3), "in_ch": 16, "mid_ch": 24, "out_ch": 64},
                {"layers": (3, 8), "in_ch": 24, "mid_ch": 48, "out_ch": 128},
                {"layers": (8, 11), "in_ch": 48, "mid_ch": 96, "out_ch": 256},
                {"layers": (11, 14), "in_ch": 96, "mid_ch": 576, "out_ch": 512},
            ],
            "final_ch": 576,
        },
        "mobile_v3_large": {
            "model": models.mobilenet_v3_large,
            "input_scale": 1.0,
            "stages": [
                {"layers": (0, 3), "in_ch": 16, "mid_ch": 24, "out_ch": 64},
                {"layers": (3, 6), "in_ch": 24, "mid_ch": 40, "out_ch": 128},
                {"layers": (6, 12), "in_ch": 40, "mid_ch": 112, "out_ch": 256},
                {"layers": (12, 15), "in_ch": 112, "mid_ch": 160, "out_ch": 512},
            ],
            "final_ch": 160,
        },
    }

    def __init__(
        self,
        model_type: str = "mobile_v3_small",
        pretrained: bool = True,
        freeze: bool = False,
    ) -> None:
        super().__init__()
        config = self.MODEL_CONFIGS[model_type]
        self.input_scale = config["input_scale"]

        base_model = config["model"](weights="DEFAULT" if pretrained else None)
        features = base_model.features

        self.stages = nn.ModuleList()
        self.adaptors = nn.ModuleList()

        for idx, sc in enumerate(config["stages"]):
            stage_layers = list(features[sc["layers"][0]:sc["layers"][1]])
            if idx == 0:
                stage_layers[0] = nn.Conv2d(
                    3, sc["in_ch"], kernel_size=3, stride=1, padding=1, bias=False,
                )
            self.stages.append(nn.Sequential(*stage_layers))

            adaptor = nn.Sequential(
                nn.Conv2d(sc["mid_ch"], sc["out_ch"], 1, bias=False),
                nn.BatchNorm2d(sc["out_ch"]),
                nn.ReLU(inplace=True),
                SEBlock(sc["out_ch"]),
            )
            self.adaptors.append(adaptor)

        self.final_conv = nn.Sequential(
            nn.Conv2d(config["final_ch"], 1024, 1, bias=False),
            nn.BatchNorm2d(1024),
            nn.ReLU(inplace=True),
        )

        if freeze:
            for param in self.stages.parameters():
                param.requires_grad = False

    def forward(self, x: torch.Tensor) -> BackboneOutputs:
        # MobileNet은 stride 구성이 달라 입력을 먼저 스케일 조정
        # (Small: 1.5배 확대, Large: 1.0배 유지)
        x = F.interpolate(x, scale_factor=self.input_scale,
                          mode="bilinear", align_corners=False)

        # 각 stage 통과 후 adaptor로 채널 수를 DetNet 표준값으로 맞춤
        # features[0~3] → relu2_2, relu3_2, relu4_3, relu5_3에 대응
        features = []
        for stage, adaptor in zip(self.stages, self.adaptors):
            x = stage(x)
            features.append(adaptor(x))

        # 마지막 stage 출력을 1024ch fc7 특징맵으로 변환
        x = self.final_conv(x)
        # BackboneOutputs: (fc7, relu5_3, relu4_3, relu3_2, relu2_2) 순서로 반환
        return BackboneOutputs(x, features[3], features[2], features[1], features[0])


class MobileDetNet(BaseDetNet):
    """MobileNetV3 backbone DetNet 모델"""

    def __init__(
        self,
        backbone_type: str = "mobile_v3_small",
        pretrained: bool = True,
        freeze: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__()

        self.backbone = MobileBackbone(backbone_type, pretrained, freeze)

        # fc7(1024) + relu5_3(512) = 1536
        self.upconv1 = DoubleConvMobile(1536, 512, 256)
        self.upconv2 = DoubleConvMobile(512, 256, 128)
        self.upconv3 = DoubleConvMobile(256, 128, 64)
        self.upconv4 = DoubleConvMobile(128, 64, 32)

        self._initialize_classifier(32)


# ===================================================================
# Factory — backbone 이름으로 모델 생성
# ===================================================================

BACKBONE_REGISTRY = {
    # VGG variants
    "VGG11_BN": ("vgg11", DetNet),
    "VGG16_BN": ("vgg16", DetNet),
    "VGG19_BN": ("vgg19", DetNet),
    # MobileNet V3 (adaptor 방식)
    "MOBILENET_V3_SMALL": ("mobile_v3_small", MobileDetNet),
    "MOBILENET_V3_LARGE": ("mobile_v3_large", MobileDetNet),
}


def build_detector(
    backbone: str = "VGG16_BN",
    pretrained: bool = False,
    freeze: bool = False,
    pretrained_weight_path: Optional[str] = None,
    **kwargs: object,
) -> nn.Module:
    """
    Backbone에 따른 DetNet 모델을 생성합니다.

    Args:
        backbone: backbone 이름 (BACKBONE_REGISTRY 참조)
        pretrained: pretrained 가중치 사용 여부
        freeze: backbone 일부 레이어 freeze 여부
        pretrained_weight_path: VGG용 pretrained 가중치 경로
        **kwargs: 모델별 추가 파라미터

    Returns:
        DetNet 모델 인스턴스
    """
    backbone = backbone.upper()

    if backbone not in BACKBONE_REGISTRY:
        raise ValueError(
            f"지원하지 않는 backbone: {backbone}. "
            f"지원 목록: {list(BACKBONE_REGISTRY.keys())}"
        )

    backbone_type, model_cls = BACKBONE_REGISTRY[backbone]

    # VGG만 pretrained_weight_path 사용
    if model_cls is DetNet:
        return model_cls(
            backbone_type=backbone_type,
            pretrained=pretrained,
            freeze=freeze,
            pretrained_weight_path=pretrained_weight_path,
            **kwargs,
        )
    else:
        return model_cls(
            backbone_type=backbone_type,
            pretrained=pretrained,
            freeze=freeze,
            **kwargs,
        )
