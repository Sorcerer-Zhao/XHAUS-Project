#!/usr/bin/env bash
# 将 Jensen_Song/skills 下的全部 Skill 符号链接到所有 OpenClaw Agent workspace。
# 可重复执行；已正确链接的会跳过。
#
# 用法:
#   ./install.sh
#   ./install.sh --uninstall   # 仅移除本脚本创建的链接

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_SRC="$SCRIPT_DIR"

WORKSPACES=(
  "$HOME/.openclaw/workspace"
  "$HOME/.openclaw/workspace-hausmeister"
  "$HOME/.openclaw/workspace-toru"
  "$HOME/.openclaw/workspace-sebas-tian"
  "$HOME/.openclaw/workspace-emma"
)

SKILL_NAMES=()
while IFS= read -r _skill; do
  SKILL_NAMES+=("$_skill")
done < <(find "$SKILLS_SRC" -mindepth 1 -maxdepth 1 -type d ! -name '.*' ! -name '_shared' -exec basename {} \; | sort)

uninstall=false
if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall=true
fi

link_skill() {
  local ws="$1"
  local skill="$2"
  local target="$ws/skills/$skill"
  local source="$SKILLS_SRC/$skill"

  mkdir -p "$ws/skills"

  if $uninstall; then
    if [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
      rm "$target"
      echo "REMOVED: $target"
    fi
    return
  fi

  if [[ -e "$target" || -L "$target" ]]; then
    if [[ -L "$target" && "$(readlink "$target")" == "$source" ]]; then
      echo "SKIP: $target"
      return
    fi
    echo "REPLACE: $target"
    rm -rf "$target"
  fi

  ln -s "$source" "$target"
  echo "LINKED: $target -> $source"
}

for ws in "${WORKSPACES[@]}"; do
  echo ""
  echo "==> $ws"
  for skill in "${SKILL_NAMES[@]}"; do
    link_skill "$ws" "$skill"
  done
done

if ! $uninstall; then
  echo ""
  echo "完成。请确认 openclaw.json 的 skills.load.allowSymlinkTargets 包含:"
  echo "  $SKILLS_SRC"
  echo ""
  echo "修改配置后重启 Gateway: openclaw gateway --port 18789"
fi
