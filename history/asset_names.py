"""Read historical asset names absent or incomplete in exported .sym files.

Format: rs3-cache Unpack.loadAssetNames; JS5 archive 67, material/font groups 32/90.
https://github.com/zwyz/rs3-cache/blob/59b566a22a9ea537c26e99701837c2c5cce4871e/src/main/java/rs3/Unpack.java
"""
import bz2
import gzip
import struct


def decode_asset_names(container: bytes) -> list[tuple[str, str]]:
    if len(container) < 5:
        raise ValueError("Truncated asset-name container")
    compression, length = struct.unpack_from(">BI", container)
    header_size = 5 if compression == 0 else 9
    if len(container) < header_size + length:
        raise ValueError("Truncated asset-name payload")
    compressed = container[header_size:header_size + length]
    if compression == 0:
        data = compressed
    elif compression == 1:
        data = bz2.decompress(b"BZh1" + compressed)
    elif compression == 2:
        data = gzip.decompress(compressed)
    else:
        raise ValueError(f"Unsupported asset-name compression: {compression}")
    if compression and len(data) != struct.unpack_from(">I", container, 5)[0]:
        raise ValueError("Asset-name decompressed length mismatch")
    if len(data) < 8:
        raise ValueError("Truncated asset-name table")
    pack_type, count = struct.unpack_from(">II", data)
    if pack_type not in {1, 2}:
        raise ValueError(f"Unsupported asset-name pack type: {pack_type}")
    entry_size = 4 if pack_type == 1 else 8
    table_start = 8 + entry_size * count
    if table_start > len(data):
        raise ValueError("Truncated asset-name offsets")
    names = []
    for index in range(count):
        if pack_type == 1:
            identifier, offset = index, struct.unpack_from(">i", data, 8 + index * 4)[0]
        else:
            identifier, offset = struct.unpack_from(">Ii", data, 8 + index * 8)
        if offset == -1:
            continue
        start = table_start + offset
        end = data.find(b"\0", start)
        if offset < 0 or start >= len(data) or end == -1:
            raise ValueError("Invalid asset-name string offset")
        names.append((str(identifier), data[start:end].decode("cp1252").lower()))
    return names
