#!/usr/bin/env python3

import argparse
import json
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COURSE_DATA_DIR = REPO_ROOT / "MasterCourse" / "CourseData"
EXPORT_MANIFEST_PATH = Path("/Volumes/wdssd/Exports/mastercourse-lesson-images/manifest.json")
REMADE_ROOT = Path("/Users/muaffakaj/Desktop/REMADE-IMAGES")
MEDIA_ROOT = REPO_ROOT / "media"
MANIFEST_OUTPUT_PATH = REPO_ROOT / "course-media-manifest.json"
REPORT_OUTPUT_PATH = REPO_ROOT / "course-media-manifest.report.json"
RAW_MEDIA_BASE_URL = "https://raw.githubusercontent.com/moufakaj/mastercourse.app/main/media/"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate course-media-manifest.json from Desktop REMADE-IMAGES"
    )
    parser.add_argument(
        "--remade-root",
        default=str(REMADE_ROOT),
        help="Path to the remade images root",
    )
    parser.add_argument(
        "--export-manifest",
        default=str(EXPORT_MANIFEST_PATH),
        help="Path to the source export manifest.json",
    )
    parser.add_argument(
        "--media-root",
        default=str(MEDIA_ROOT),
        help="Repo-local output media folder",
    )
    parser.add_argument(
        "--manifest-output",
        default=str(MANIFEST_OUTPUT_PATH),
        help="Output course-media-manifest.json path",
    )
    parser.add_argument(
        "--report-output",
        default=str(REPORT_OUTPUT_PATH),
        help="Output report path",
    )
    parser.add_argument(
        "--media-base-url",
        default=RAW_MEDIA_BASE_URL,
        help="Base URL prefix used in generated manifest values",
    )
    parser.add_argument(
        "--clean-media",
        action="store_true",
        help="Delete the existing media output folder before copying remade assets",
    )
    return parser.parse_args()


def ordered(items):
    return sorted(
        enumerate(items),
        key=lambda pair: (pair[1].get("ordering", pair[0]), pair[0]),
    )


def block_identifier(block, unit_index, lesson_index, screen_index, block_index):
    raw_id = str(block.get("id", "")).strip()
    if raw_id:
        return raw_id
    return f"unit-{unit_index}-lesson-{lesson_index}-screen-{screen_index}-block-{block_index}"


def media_value_from_option(option):
    for key in ("media_url", "image_url", "image"):
        value = option.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def load_export_rows(export_manifest_path):
    rows = json.loads(export_manifest_path.read_text())["images"]
    rows = [row for row in rows if Path(row["local_path"]).suffix.lower() != ".gif"]
    by_block_id = {}
    by_stem = {}
    for row in rows:
        block_id = row["block_id"]
        local_path = Path(row["local_path"])
        by_block_id[block_id] = row
        by_stem[local_path.stem] = row
    return rows, by_block_id, by_stem


def collect_remade_images(remade_root):
    remade_files = [
        path for path in remade_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".webp", ".png", ".jpg", ".jpeg"}
    ]
    by_stem = {}
    for path in remade_files:
        by_stem[path.stem] = path
    return remade_files, by_stem


def build_slot_manifest(course_data_dir, export_rows_by_block_id, remade_root, remade_by_stem):
    slots = {}
    media_copies = []
    report = {
        "lesson_slots_replaced_with_remade": [],
        "lesson_slots_missing_remade": [],
        "lesson_video_slots_passthrough": [],
        "option_media_slots_passthrough": [],
        "orphan_remade_images": [],
    }

    for course_path in sorted(course_data_dir.glob("*.json")):
        resource_name = course_path.stem
        course_root = json.loads(course_path.read_text())
        units = [item for _, item in ordered(course_root.get("units", []))]

        for unit_index, unit in enumerate(units):
            lessons = [item for _, item in ordered(unit.get("lessons", []))]

            for lesson_index, lesson in enumerate(lessons):
                screens = [item for _, item in ordered(lesson.get("screens", []))]

                for screen_index, screen in enumerate(screens):
                    blocks = [item for _, item in ordered(screen.get("blocks", []))]

                    for block_index, block in enumerate(blocks):
                        block_type = str(block.get("type", ""))
                        media_url = block.get("media_url")
                        slot_key = f"{resource_name}/{block_identifier(block, unit_index, lesson_index, screen_index, block_index)}"
                        metadata = block.get("metadata") if isinstance(block.get("metadata"), dict) else {}

                        if block_type == "image" and isinstance(media_url, str) and media_url.strip():
                            block_id = str(block.get("id", "")).strip()
                            export_row = export_rows_by_block_id.get(block_id)
                            if export_row:
                                source_stem = Path(export_row["local_path"]).stem
                                remade_path = remade_by_stem.get(source_stem)
                                if remade_path:
                                    remade_rel = remade_path.relative_to(remade_root)
                                    slots[slot_key] = remade_rel.as_posix()
                                    media_copies.append((remade_path, remade_rel))
                                    report["lesson_slots_replaced_with_remade"].append(
                                        {
                                            "slot": slot_key,
                                            "block_id": block_id,
                                            "local_path": export_row["local_path"],
                                            "remade_path": str(remade_path),
                                        }
                                    )
                                else:
                                    report["lesson_slots_missing_remade"].append(
                                        {
                                            "slot": slot_key,
                                            "block_id": block_id,
                                            "local_path": export_row["local_path"],
                                        }
                                    )
                            else:
                                slots[slot_key] = media_url.strip()
                        elif block_type == "video" and isinstance(media_url, str) and media_url.strip():
                            slots[slot_key] = media_url.strip()
                            report["lesson_video_slots_passthrough"].append(slot_key)

                        options = metadata.get("options")
                        if isinstance(options, list):
                            for option_index, option in enumerate(options):
                                if not isinstance(option, dict):
                                    continue
                                option_media = media_value_from_option(option)
                                if option_media:
                                    slots[f"{slot_key}/option-{option_index}"] = option_media
                                    report["option_media_slots_passthrough"].append(
                                        f"{slot_key}/option-{option_index}"
                                    )

    used_stems = {
        Path(entry["remade_path"]).stem
        for entry in report["lesson_slots_replaced_with_remade"]
    }
    for stem, path in remade_by_stem.items():
        if stem not in used_stems:
            report["orphan_remade_images"].append(str(path))

    return slots, media_copies, report


def copy_media(media_copies, media_root, clean_media):
    if clean_media and media_root.exists():
        shutil.rmtree(media_root)
    media_root.mkdir(parents=True, exist_ok=True)

    copied = []
    seen = set()
    for source_path, relative_path in media_copies:
        if relative_path in seen:
            continue
        seen.add(relative_path)
        destination = media_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        copied.append(destination)
    return copied


def rewrite_slot_values(slots, media_base_url):
    prefix = media_base_url.rstrip("/") + "/"
    rewritten = {}
    for key, value in slots.items():
        if value.lower().startswith("http://") or value.lower().startswith("https://"):
            rewritten[key] = value
        else:
            rewritten[key] = prefix + value.lstrip("/")
    return rewritten


def main():
    args = parse_args()

    remade_root = Path(args.remade_root)
    export_manifest_path = Path(args.export_manifest)
    media_root = Path(args.media_root)
    manifest_output_path = Path(args.manifest_output)
    report_output_path = Path(args.report_output)

    export_rows, export_rows_by_block_id, _ = load_export_rows(export_manifest_path)
    remade_files, remade_by_stem = collect_remade_images(remade_root)
    slots, media_copies, report = build_slot_manifest(
        COURSE_DATA_DIR,
        export_rows_by_block_id,
        remade_root,
        remade_by_stem,
    )

    copied = copy_media(media_copies, media_root, clean_media=args.clean_media)
    rewritten_slots = rewrite_slot_values(slots, args.media_base_url)

    manifest_output_path.write_text(
        json.dumps({"slots": dict(sorted(rewritten_slots.items()))}, indent=2) + "\n"
    )

    report_summary = {
        "export_manifest_rows": len(export_rows),
        "remade_images_found": len(remade_files),
        "lesson_slots_replaced_with_remade": len(report["lesson_slots_replaced_with_remade"]),
        "lesson_slots_missing_remade": len(report["lesson_slots_missing_remade"]),
        "lesson_video_slots_passthrough": len(report["lesson_video_slots_passthrough"]),
        "option_media_slots_passthrough": len(report["option_media_slots_passthrough"]),
        "media_files_copied": len(copied),
        "orphan_remade_images": len(report["orphan_remade_images"]),
    }
    report_output_path.write_text(
        json.dumps(
            {
                "summary": report_summary,
                "details": report,
            },
            indent=2,
        ) + "\n"
    )

    print(json.dumps(report_summary, indent=2))
    print(f"Manifest written to {manifest_output_path}")
    print(f"Report written to {report_output_path}")


if __name__ == "__main__":
    main()
