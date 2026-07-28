from logging import getLogger
from pathlib import Path

logger = getLogger(__name__)

_CORE_ROOT = Path(__file__).parent.parent
_PROTO_DIR = _CORE_ROOT / "sources" / "proto"


def generate() -> int:
    """
    Regenerate `sources/proto/*_pb2.py` (and `.pyi` stubs) from `sources/proto/*.proto`, using
    `grpcio-tools`' bundled `protoc`. Requires the `devel` extra.
    :return: exit code integer.
    """

    proto_files = [str(path) for path in _PROTO_DIR.glob("*.proto")]
    if not proto_files:
        logger.info("No .proto files found, nothing to generate.")
        return 0

    from grpc_tools import protoc

    args = ["protoc", f"-I{_PROTO_DIR}", f"--python_out={_PROTO_DIR}", f"--pyi_out={_PROTO_DIR}", *proto_files]
    return int(protoc.main(args))
