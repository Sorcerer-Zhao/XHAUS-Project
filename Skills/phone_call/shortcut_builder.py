"""OpenClaw 预约拨号 — 与 iPhone 实测可用流程对齐（无 If / 无 callAt 等待）。

iPhone：我的 iPhone → Shortcuts → current.json
流程：读 current → 弹出台词 → 菜单拨打/取消
"""

from __future__ import annotations

import plistlib
import uuid
from pathlib import Path

SHORTCUT_NAME = "预约拨号v2.0"
BUNDLE_FOLDER_NAME = "Openclaw-PhoneCall"
IPHONE_DATA_FOLDER = "Shortcuts"
CURRENT_JSON_NAME = "current.json"
CURRENT_VAR = "current"
IPHONE_JSON_LOCATION_HINT = f"「文件」→ 我的 iPhone → {IPHONE_DATA_FOLDER}/"
FILE_STORAGE = "Local"


def _uid() -> str:
    return str(uuid.uuid4()).upper()


def _attach(output_uuid: str, output_name: str) -> dict:
    return {
        "Value": {
            "OutputUUID": output_uuid,
            "Type": "ActionOutput",
            "OutputName": output_name,
        },
        "WFSerializationType": "WFTextTokenAttachment",
    }


def _open_relative(file_uuid: str, file_name: str, output_name: str) -> dict:
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.documentpicker.open",
        "WFWorkflowActionParameters": {
            "UUID": file_uuid,
            "WFShowFilePicker": False,
            "WFFileErrorIfNotFound": True,
            "WFGetFilePath": file_name,
            "WFGetFileInitialDirectoryPath": IPHONE_DATA_FOLDER,
            "WFFileStorageService": FILE_STORAGE,
            "CustomOutputName": output_name,
        },
    }


def _show_script_alert(script_uuid: str) -> dict:
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.alert",
        "WFWorkflowActionParameters": {
            "UUID": _uid(),
            "WFAlertActionTitle": "📞 订位稿",
            "WFAlertActionMessage": _attach(script_uuid, "订位稿"),
            "WFAlertActionCancelButtonShown": True,
        },
    }


def _menu_cancel_call(menu_group: str, tel_uuid: str) -> list[dict]:
    return [
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.choosefrommenu",
            "WFWorkflowActionParameters": {
                "UUID": _uid(),
                "WFMenuItems": ["取消", "拨打"],
                "WFMenuPrompt": "是否拨打？",
                "WFControlFlowMode": 0,
                "GroupingIdentifier": menu_group,
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.choosefrommenu",
            "WFWorkflowActionParameters": {
                "UUID": _uid(),
                "WFMenuItemTitle": "取消",
                "WFControlFlowMode": 1,
                "GroupingIdentifier": menu_group,
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.exit",
            "WFWorkflowActionParameters": {"UUID": _uid()},
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.choosefrommenu",
            "WFWorkflowActionParameters": {
                "UUID": _uid(),
                "WFMenuItemTitle": "拨打",
                "WFControlFlowMode": 1,
                "GroupingIdentifier": menu_group,
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.openurl",
            "WFWorkflowActionParameters": {
                "UUID": _uid(),
                "WFInput": _attach(tel_uuid, "电话链接"),
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.choosefrommenu",
            "WFWorkflowActionParameters": {
                "UUID": _uid(),
                "WFControlFlowMode": 2,
                "GroupingIdentifier": menu_group,
            },
        },
    ]


def _parse_json_dictionary(dict_uuid: str, input_uuid: str, input_name: str) -> dict:
    """从 current.json 解析为词典（iPhone 上 getvalueforkey 需要 Dictionary 类型）。"""
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.detect.dictionary",
        "WFWorkflowActionParameters": {
            "UUID": dict_uuid,
            "WFInput": _attach(input_uuid, input_name),
            "CustomOutputName": "预约数据",
        },
    }


def build_workflow() -> dict:
    file_uuid = _uid()
    dict_uuid = _uid()
    script_uuid = _uid()
    tel_uuid = _uid()
    menu_group = _uid()

    actions = [
        _open_relative(file_uuid, CURRENT_JSON_NAME, CURRENT_VAR),
        _parse_json_dictionary(dict_uuid, file_uuid, CURRENT_VAR),
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": script_uuid,
                "WFDictionaryKey": "script",
                "WFInput": _attach(dict_uuid, "预约数据"),
                "CustomOutputName": "订位稿",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
            "WFWorkflowActionParameters": {
                "UUID": tel_uuid,
                "WFDictionaryKey": "tel",
                "WFInput": _attach(dict_uuid, "预约数据"),
                "CustomOutputName": "电话链接",
            },
        },
        _show_script_alert(script_uuid),
        *_menu_cancel_call(menu_group, tel_uuid),
    ]

    return {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowClientVersion": "2302.0.4",
        "WFWorkflowClientRelease": "2302.0.4",
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 4271456283,
            "WFWorkflowIconGlyphNumber": 59742,
        },
        "WFWorkflowTypes": ["NCWidget", "WatchKit"],
        "WFWorkflowInputContentItemClasses": ["WFStringContentItem"],
        "WFWorkflowActions": actions,
    }


def write_unsigned_shortcut(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        plistlib.dump(build_workflow(), f, fmt=plistlib.FMT_BINARY)
