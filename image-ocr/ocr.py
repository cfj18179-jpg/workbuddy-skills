#!/usr/bin/env python3
"""
Image OCR Script — supports 腾讯云 OCR and 阿里云 OCR.

Usage:
    python3 ocr.py <image_path> [--provider tencent|alibaba] [--lang zh|auto|en|...] [--json]

Environment variables:
    腾讯云:
        TENCENTCLOUD_SECRET_ID  — SecretId
        TENCENTCLOUD_SECRET_KEY — SecretKey
    阿里云:
        ALIBABA_CLOUD_ACCESS_KEY_ID     — AccessKey ID
        ALIBABA_CLOUD_ACCESS_KEY_SECRET — AccessKey Secret

Output:
    Plain text (default) or JSON (--json) of recognized text.
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path


# ── Helpers ────────────────────────────────────────────────────────────────

def read_image_base64(image_path: str) -> str:
    """Read an image file and return base64-encoded string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def check_credentials(provider: str) -> dict:
    """Check that required env vars are set for the given provider."""
    env_map = {
        "tencent": {
            "id": "TENCENTCLOUD_SECRET_ID",
            "key": "TENCENTCLOUD_SECRET_KEY",
        },
        "alibaba": {
            "id": "ALIBABA_CLOUD_ACCESS_KEY_ID",
            "key": "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
        },
    }
    if provider not in env_map:
        raise ValueError(f"Unknown provider: {provider}")

    cfg = env_map[provider]
    missing = []
    for k in (cfg["id"], cfg["key"]):
        if not os.environ.get(k):
            missing.append(k)

    if missing:
        print(
            f"\n❌ 缺少 {provider} 认证凭据，请设置以下环境变量：\n"
            + "\n".join(f"   export {m}=<your-value>" for m in missing)
            + "\n",
            file=sys.stderr,
        )
        sys.exit(1)

    return {
        "id": os.environ[cfg["id"]],
        "key": os.environ[cfg["key"]],
    }


# ── 腾讯云 OCR ─────────────────────────────────────────────────────────────

def ocr_tencent(image_path: str, language_type: str = "zh") -> dict:
    """Use 腾讯云 GeneralBasicOCR to recognize text in an image."""
    try:
        from tencentcloud.common import credential
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
            TencentCloudSDKException,
        )
        from tencentcloud.ocr.v20181119 import ocr_client, models
    except ImportError:
        print(
            "\n❌ 未安装 tencentcloud-sdk-python，请运行：\n"
            "   pip install tencentcloud-sdk-python\n",
            file=sys.stderr,
        )
        sys.exit(1)

    creds = check_credentials("tencent")
    cred = credential.Credential(creds["id"], creds["key"])
    client = ocr_client.OcrClient(cred, "ap-guangzhou")

    req = models.GeneralBasicOCRRequest()
    req.ImageBase64 = read_image_base64(image_path)
    req.LanguageType = language_type

    try:
        resp = client.GeneralBasicOCR(req)
    except TencentCloudSDKException as e:
        print(f"\n❌ 腾讯云 OCR 调用失败: {e}\n", file=sys.stderr)
        sys.exit(1)

    # Build result
    text_lines = []
    detections = []
    for item in resp.TextDetections:
        text_lines.append(item.DetectedText)
        detections.append({
            "text": item.DetectedText,
            "confidence": item.Confidence,
        })

    return {
        "provider": "tencent",
        "full_text": "\n".join(text_lines),
        "lines": detections,
        "language": resp.Language or "",
        "angle": resp.Angle or 0,
        "raw": str(resp),
    }


# ── 阿里云 OCR ─────────────────────────────────────────────────────────────

def ocr_alibaba(image_path: str) -> dict:
    """Use 阿里云 RecognizeGeneral to recognize text in an image."""
    try:
        from alibabacloud_ocr_api20210707.client import Client
        from alibabacloud_ocr_api20210707 import models as ocr_models
        from alibabacloud_tea_openapi import models as open_api_models
    except ImportError:
        print(
            "\n❌ 未安装阿里云 OCR SDK，请运行：\n"
            "   pip install alibabacloud_ocr_api20210707\n",
            file=sys.stderr,
        )
        sys.exit(1)

    creds = check_credentials("alibaba")

    config = open_api_models.Config(
        access_key_id=creds["id"],
        access_key_secret=creds["key"],
    )
    config.endpoint = "ocr-api.cn-hangzhou.aliyuncs.com"

    client = Client(config)

    # Read image bytes
    with open(image_path, "rb") as f:
        body = f.read()

    request = ocr_models.RecognizeGeneralRequest()
    request.body = body

    try:
        response = client.recognize_general(request)
    except Exception as e:
        print(f"\n❌ 阿里云 OCR 调用失败: {e}\n", file=sys.stderr)
        sys.exit(1)

    # Parse response
    data_str = response.body.data  # JSON string
    data = json.loads(data_str) if isinstance(data_str, str) else data_str

    content = data.get("content", "")
    words_info = data.get("prism_wordsInfo", [])

    text_lines = [
        w.get("word", "") for w in words_info
    ] if words_info else content.split("\n") if content else []

    detections = []
    for w in words_info:
        detections.append({
            "text": w.get("word", ""),
            "confidence": w.get("prob", 0),
        })

    return {
        "provider": "alibaba",
        "full_text": content.strip() if content else "\n".join(text_lines),
        "lines": detections,
        "width": data.get("width", 0),
        "height": data.get("height", 0),
        "raw": data_str,
    }


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="图片 OCR 文字识别 — 支持腾讯云/阿里云",
    )
    parser.add_argument("image", help="图片文件路径")
    parser.add_argument(
        "--provider",
        choices=["tencent", "alibaba"],
        default="tencent",
        help="OCR 服务商 (default: tencent)",
    )
    parser.add_argument(
        "--lang",
        default="zh",
        help="识别语言 (腾讯云: zh/auto/en/jap/kor/...；阿里云默认自动)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出完整结果",
    )
    args = parser.parse_args()

    # Validate image path
    image_path = Path(args.image)
    if not image_path.exists():
        print(f"\n❌ 文件不存在: {args.image}\n", file=sys.stderr)
        sys.exit(1)
    if image_path.suffix.lower() not in (
        ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp", ".pdf",
    ):
        print(
            f"\n⚠️  文件类型可能不支持: {image_path.suffix}\n"
            "   支持的格式: PNG, JPG, JPEG, BMP, GIF, TIFF, WebP, PDF\n",
            file=sys.stderr,
        )

    # Dispatch
    if args.provider == "tencent":
        result = ocr_tencent(str(image_path), args.lang)
    else:
        result = ocr_alibaba(str(image_path))

    # Output
    if args.json:
        # Remove raw field for cleaner JSON output
        output = {k: v for k, v in result.items() if k != "raw"}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        full_text = result.get("full_text", "")
        if not full_text:
            print("(未识别到任何文字)", file=sys.stderr)
            sys.exit(0)
        print(full_text)


if __name__ == "__main__":
    main()
