import json
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[3]
OFFICIAL = (
    SOURCE_ROOT / "substance3d_chinese_translator" / "translations"
    / "official_assets_zh.json"
)
INPUTS = [
    Path.home() / "Desktop" / "1.json",
    Path.home() / "Desktop" / "2.json",
]


def load_translations(path):
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    translations = payload.get("translations")
    if not isinstance(translations, dict):
        raise ValueError(f"缺少 translations 对象: {path}")
    return translations


def main():
    payload = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    translations = payload["translations"]
    added = 0
    duplicates = 0
    conflicts = 0

    for source_path in INPUTS:
        for source, target in load_translations(source_path).items():
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            source = source.strip()
            target = target.strip()
            if not source or not target:
                continue
            if source not in translations:
                translations[source] = target
                added += 1
            elif translations[source] == target:
                duplicates += 1
            else:
                # The reviewed official dictionary is authoritative for an
                # existing key; external packages only contribute new keys.
                conflicts += 1

    payload.setdefault("merge", {})
    payload["merge"].update({
        "sources": [path.name for path in INPUTS],
        "added_entries": added,
        "identical_duplicates": duplicates,
        "preserved_official_conflicts": conflicts,
    })
    OFFICIAL.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"added={added} duplicates={duplicates} conflicts={conflicts} "
        f"total={len(translations)}"
    )


if __name__ == "__main__":
    main()
