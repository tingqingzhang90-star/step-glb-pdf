# -*- coding: utf-8 -*-
"""结果存储抽象层:本地文件系统(默认)或 S3 兼容对象存储(OSS/COS/MinIO/S3)。

设计目标:
  * 本地 output/ 仍是管线的"工作存储"——所有既有的写盘/读盘/HTTP 服务逻辑
    保持不变,本模块只在"结果产出后"把文件镜像到对象存储,以及在对外服务路由
    上可选地 302 到对象存储外链(前端无需改动)。
  * 上传/签名失败不影响主流程(被 try/except 吞掉并打到 stderr)。
  * OSS 配置缺失或未开启时,所有方法都是 no-op,与改造前行为完全一致。

配置(项目根 .env,由 web/env_settings 在启动时载入 os.environ):
  STORAGE_BACKEND=local | oss          默认 local
  # ---- OSS(S3 兼容协议:阿里云 OSS / 腾讯云 COS / MinIO / AWS S3 通用)----
  OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
  OSS_REGION=cn-hangzhou
  OSS_BUCKET=my-bucket
  OSS_ACCESS_KEY_ID=
  OSS_ACCESS_KEY_SECRET=
  OSS_PREFIX=step-output               对象存储中的 key 前缀(可空)
  OSS_PUBLIC_BASE=                     留空=用临时签名 URL(默认 1h);
                                        填了=用公开基址(CDN),如
                                        https://cdn.example.com/step-output
  OSS_PRESIGN_EXPIRE=3600              签名 URL 有效期(秒)

注意:S3 兼容模式下 endpoint 必须是对象存储的 S3 接入域名;阿里 OSS / 腾讯 COS
都提供 S3 兼容端点,MinIO 填 http://<host>:9000 即可。
"""
import os
import sys

from core import paths


class Storage:
    """存储后端基类。key 一律为相对 output/ 的路径(如 250-X/drawing.pdf)。"""

    def enabled(self):
        """是否真正启用了远端(OSS);local 下为 False"""
        return False

    def publish(self, abs_path):
        """把本地落盘文件(abs_path,须位于 output/ 下)同步到远端;local 下空操作"""
        raise NotImplementedError

    def publish_dir(self, abs_dir):
        if not os.path.isdir(abs_dir):
            return
        for root, _, files in os.walk(abs_dir):
            for name in files:
                self.publish(os.path.join(root, name))

    def publish_model(self, model_code):
        self.publish_dir(os.path.join(paths.OUT_DIR, model_code))

    def url(self, rel):
        """rel 为相对 output/ 的路径;返回可外链 URL 或 None(local)"""
        return None


class LocalStorage(Storage):
    def enabled(self):
        return False

    def publish(self, abs_path):
        return None


class OssStorage(Storage):
    def __init__(self, endpoint, region, bucket, ak, sk, prefix, public_base, presign):
        self.endpoint = (endpoint or "").strip()
        self.region = (region or "").strip()
        self.bucket = (bucket or "").strip()
        self.ak = ak or ""
        self.secret = sk or ""
        self.prefix = (prefix or "").strip().strip("/")
        self.public_base = (public_base or "").strip().rstrip("/")
        self.presign = int(presign or 3600)
        self._client = None

    def enabled(self):
        return True

    @property
    def client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint or None,
                region_name=self.region or None,
                aws_access_key_id=self.ak or None,
                aws_secret_access_key=self.secret or None,
            )
        return self._client

    def _key(self, rel):
        rel = rel.replace("\\", "/").strip("/")
        return f"{self.prefix}/{rel}" if self.prefix else rel

    def publish(self, abs_path):
        if not abs_path or not os.path.isfile(abs_path):
            return
        rel = _rel_to_out(abs_path)
        if rel is None:
            return
        try:
            self.client.upload_file(abs_path, self.bucket, self._key(rel))
        except Exception as exc:  # 上传失败绝不阻断主流程
            _log_error(f"上传失败 {rel}", exc)

    def url(self, rel):
        if not rel:
            return None
        rel = rel.replace("\\", "/").strip("/")
        if self.public_base:
            return f"{self.public_base}/{rel}"
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": self._key(rel)},
                ExpiresIn=self.presign,
            )
        except Exception as exc:
            _log_error(f"签名失败 {rel}", exc)
            return None


def _rel_to_out(abs_path):
    """绝对路径 → 相对 output/ 的路径;不在 output/ 下返回 None(不上传)"""
    out_root = os.path.abspath(paths.OUT_DIR)
    ap = os.path.abspath(abs_path)
    if ap.startswith(out_root + os.sep):
        return os.path.relpath(ap, out_root).replace("\\", "/")
    return None


def _log_error(what, exc):
    try:
        sys.stderr.write(f"[storage] OSS {what}: {exc}\n")
    except Exception:
        pass


_storage = None


def get_storage():
    """返回进程内单例;首次调用时按 STORAGE_BACKEND 决定后端(默认 local)"""
    global _storage
    if _storage is None:
        backend = (os.environ.get("STORAGE_BACKEND") or "local").strip().lower()
        if backend == "oss":
            _storage = OssStorage(
                endpoint=os.environ.get("OSS_ENDPOINT", ""),
                region=os.environ.get("OSS_REGION", ""),
                bucket=os.environ.get("OSS_BUCKET", ""),
                ak=os.environ.get("OSS_ACCESS_KEY_ID", ""),
                sk=os.environ.get("OSS_ACCESS_KEY_SECRET", ""),
                prefix=os.environ.get("OSS_PREFIX", ""),
                public_base=os.environ.get("OSS_PUBLIC_BASE", ""),
                presign=os.environ.get("OSS_PRESIGN_EXPIRE", "3600"),
            )
        else:
            _storage = LocalStorage()
    return _storage


# ---- 便捷转发,供业务代码一行调用 ----
def publish(abs_path):
    return get_storage().publish(abs_path)


def publish_dir(abs_dir):
    return get_storage().publish_dir(abs_dir)


def publish_model(model_code):
    return get_storage().publish_model(model_code)


def url(rel):
    return get_storage().url(rel)
