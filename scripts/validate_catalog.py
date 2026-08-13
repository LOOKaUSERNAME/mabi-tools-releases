"""Validate the committed MabiTools release catalogue without network access."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "LOOKaUSERNAME/mabi-tools-releases"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
COMMIT_UTC_CALVER = re.compile(
    r"^(?P<year>\d{4})\.(?P<month>[1-9]|1[0-2])\."
    r"(?P<day>\d{2})(?:\.(?P<revision>[1-9]\d*))?$"
)
PRODUCT_ID = "hm"
TAG_PREFIX = "hm"
SOURCE_ASSET_SUFFIXES = {
    ".bat",
    ".cmd",
    ".cs",
    ".csproj",
    ".js.map",
    ".jsx",
    ".map",
    ".ps1",
    ".psm1",
    ".py",
    ".sh",
    ".sln",
    ".ts",
    ".tsx",
}


def is_hotkey_manager_installer(
    product: dict,
    version: str,
    role: object,
    name: object,
) -> bool:
    """Return whether one asset is HM's exact public Windows installer."""
    return (
        product.get("id") == "hm"
        and product.get("releaseAssetPolicy") == "windows-installer"
        and role == "installer"
        and name == f"MabiTools-Hotkey-Manager-{version}-Setup-x64.exe"
    )


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_version(
    version: str,
    product: dict,
    context: str,
) -> None:
    require(
        product.get("versioning") == "commit-utc-calver",
        f"{context}: unsupported versioning scheme",
    )
    match = COMMIT_UTC_CALVER.fullmatch(version)
    require(match is not None, f"{context}: invalid commit UTC calendar version {version}")
    assert match is not None
    try:
        date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError as error:
        raise ValueError(f"{context}: invalid calendar date in version {version}") from error
    revision = match.group("revision")
    require(
        revision is None or int(revision) <= 65535,
        f"{context}: version revision exceeds the Windows metadata limit",
    )


def validate_assets(
    assets: object,
    central_tag: str,
    context: str,
    product: dict,
    version: str,
) -> None:
    require(isinstance(assets, list) and bool(assets), f"{context}: assets must be a non-empty list")
    if product.get("releaseAssetPolicy") == "windows-installer":
        require(
            len(assets) == 1,
            f"{context}: Hotkey Manager releases must contain exactly one installer",
        )
    names: set[str] = set()
    roles: set[str] = set()
    for asset in assets:
        require(isinstance(asset, dict), f"{context}: every asset must be an object")
        name = asset.get("name")
        role = asset.get("role")
        require(isinstance(name, str) and name == Path(name).name, f"{context}: unsafe asset name")
        lowered_name = name.lower()
        hotkey_manager_installer = is_hotkey_manager_installer(
            product,
            version,
            role,
            name,
        )
        if product.get("releaseAssetPolicy") == "windows-installer":
            require(
                hotkey_manager_installer,
                f"{context}: Hotkey Manager releases allow only the versioned Windows installer",
            )
        require(
            not any(lowered_name.endswith(suffix) for suffix in SOURCE_ASSET_SUFFIXES),
            f"{context}: public source asset is not allowed: {name}",
        )
        require(
            not lowered_name.endswith(".pyw"),
            f"{context}: public Python application source is not allowed: {name}",
        )
        require(
            not re.search(r"(^|[-_.])(source|sources|src)([-_.]|$)", lowered_name),
            f"{context}: source archive is not allowed: {name}",
        )
        require(isinstance(role, str) and bool(role), f"{context}: missing asset role")
        require(name not in names, f"{context}: duplicate asset name {name}")
        require(role not in roles, f"{context}: duplicate asset role {role}")
        names.add(name)
        roles.add(role)
        require(isinstance(asset.get("size"), int) and asset["size"] > 0, f"{context}: invalid size for {name}")
        require(isinstance(asset.get("sha256"), str) and SHA256.fullmatch(asset["sha256"]) is not None,
                f"{context}: invalid SHA-256 for {name}")
        expected_url = f"https://github.com/{REPOSITORY}/releases/download/{central_tag}/{name}"
        require(asset.get("downloadUrl") == expected_url, f"{context}: wrong download URL for {name}")


def validate_record(
    path: Path,
    product: dict,
    channel_name: str,
) -> dict:
    record = read_json(path)
    context = str(path.relative_to(ROOT))
    product_id = product["id"]
    version = record.get("version")
    expected_tag = f"{TAG_PREFIX}-v{version}"
    require(record.get("schemaVersion") == 1, f"{context}: unsupported schema")
    require(record.get("productId") == product_id, f"{context}: product mismatch")
    require(record.get("channel") == channel_name, f"{context}: channel mismatch")
    require(isinstance(version, str) and bool(version), f"{context}: missing version")
    validate_version(version, product, context)
    require(path.name == f"{version}.json", f"{context}: record filename does not match version")
    require(record.get("centralTag") == expected_tag, f"{context}: central tag mismatch")
    require(record.get("releaseUrl") == f"https://github.com/{REPOSITORY}/releases/tag/{expected_tag}",
            f"{context}: central release URL mismatch")
    require(isinstance(record.get("cataloguedAt"), str) and ISO_UTC.fullmatch(record["cataloguedAt"]) is not None,
            f"{context}: invalid catalogue timestamp")

    source = record.get("source")
    require(isinstance(source, dict), f"{context}: missing source provenance")
    expected_repository = product["sourceRepository"].removeprefix("https://github.com/")
    require(source.get("repository") == expected_repository, f"{context}: source repository mismatch")
    require(source.get("tag") == f"v{version}", f"{context}: source tag mismatch")
    require(isinstance(source.get("tagObject"), str) and GIT_SHA.fullmatch(source["tagObject"]) is not None,
            f"{context}: invalid source tag object")
    require(isinstance(source.get("commit"), str) and GIT_SHA.fullmatch(source["commit"]) is not None,
            f"{context}: invalid source commit")
    require(
        isinstance(source.get("publishedAt"), str)
        and ISO_UTC.fullmatch(source["publishedAt"]) is not None,
        f"{context}: invalid source publication timestamp",
    )
    require(source.get("releaseUrl") == f"https://github.com/{expected_repository}/releases/tag/v{version}",
            f"{context}: source release URL mismatch")
    validate_assets(
        record.get("assets"),
        expected_tag,
        context,
        product,
        version,
    )
    return record


def validate_channel(path: Path, product: dict, channel_name: str) -> None:
    channel = read_json(path)
    context = str(path.relative_to(ROOT))
    product_id = product["id"]
    require(channel.get("schemaVersion") == 1, f"{context}: unsupported schema")
    require(channel.get("productId") == product_id, f"{context}: product mismatch")
    require(channel.get("channel") == channel_name, f"{context}: channel mismatch")
    require(isinstance(channel.get("updatedAt"), str) and ISO_UTC.fullmatch(channel["updatedAt"]) is not None,
            f"{context}: invalid update timestamp")

    raw_prefix = f"https://raw.githubusercontent.com/{REPOSITORY}/main/"
    record_url = channel.get("recordUrl")
    require(isinstance(record_url, str) and record_url.startswith(raw_prefix), f"{context}: invalid record URL")
    record_path = ROOT / record_url.removeprefix(raw_prefix)
    require(record_path.is_file(), f"{context}: record file does not exist")
    record = validate_record(
        record_path,
        product,
        channel_name,
    )

    release = channel.get("release")
    require(isinstance(release, dict), f"{context}: missing current release")
    expected_release = {
        "version": record["version"],
        "centralTag": record["centralTag"],
        "releaseUrl": record["releaseUrl"],
        "source": {
            "repository": record["source"]["repository"],
            "tag": record["source"]["tag"],
            "commit": record["source"]["commit"],
        },
        "assets": record["assets"],
    }
    require(release == expected_release, f"{context}: channel does not match its immutable record")


def main() -> None:
    products_document = read_json(ROOT / "products.json")
    require(products_document.get("schemaVersion") == 1, "products.json: unsupported schema")
    products = products_document.get("products")
    require(isinstance(products, list) and bool(products), "products.json: products must be a non-empty list")
    seen: set[str] = set()
    channel_count = 0
    for product in products:
        require(isinstance(product, dict), "products.json: every product must be an object")
        product_id = product.get("id")
        require(product_id == PRODUCT_ID, f"products.json: unsupported product ID {product_id!r}")
        require(product_id not in seen, f"products.json: duplicate product ID {product_id}")
        seen.add(product_id)
        require(
            product.get("versioning") == "commit-utc-calver",
            f"products.json: unsupported versioning for {product_id}",
        )
        release_asset_policy = product.get("releaseAssetPolicy")
        require(
            product_id != "hm" or release_asset_policy == "windows-installer",
            "products.json: Hotkey Manager must use the windows-installer asset policy",
        )
        channels = product.get("channels")
        require(isinstance(channels, dict) and bool(channels), f"products.json: {product_id} has no channels")
        catalog_root = ROOT / "catalog" / product_id / "releases"
        record_paths = sorted(catalog_root.glob("*.json"))
        require(bool(record_paths), f"products.json: {product_id} has no release records")
        for record_path in record_paths:
            record_header = read_json(record_path)
            record_channel = record_header.get("channel")
            require(
                isinstance(record_channel, str) and record_channel in channels,
                f"{record_path.relative_to(ROOT)}: unknown channel",
            )
            validate_record(
                record_path,
                product,
                record_channel,
            )
        for channel_name, channel_url in channels.items():
            expected_url = (
                f"https://raw.githubusercontent.com/{REPOSITORY}/main/"
                f"channels/{product_id}/{channel_name}.json"
            )
            require(channel_url == expected_url, f"products.json: wrong {product_id}/{channel_name} URL")
            validate_channel(ROOT / f"channels/{product_id}/{channel_name}.json", product, channel_name)
            channel_count += 1
    print(f"Validated {len(products)} products and {channel_count} release channels.")


if __name__ == "__main__":
    main()
