from . import app as runtime
from .device_auth_patch import install

install(runtime)

__all__ = ["runtime"]
