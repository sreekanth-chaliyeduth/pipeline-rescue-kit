#!/bin/sh
# Changed-module selector.
#
# Maps changed paths to Maven module directories using git diff. Maven itself
# resolves upstream (-am) and downstream (-amd) modules. Root build files,
# unknown POMs and any unrecognised path fail safe to full scope. The five
# known non-Maven service directories select nothing. Documentation, image and
# deployment paths select nothing only outside Maven module directories.
set -u

REPO="."
REFERENCE=""
HEAD="HEAD"
ROOT_POM="pom.xml"

usage() {
    echo "usage: select-modules.sh --repo DIR --reference COMMIT [--head COMMIT]" >&2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --repo) REPO="$2"; shift 2 ;;
        --reference) REFERENCE="$2"; shift 2 ;;
        --head) HEAD="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage; exit 2 ;;
    esac
done

shell_quote() {
    printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

emit_full() {
    printf "PRK_MODE='full'\n"
    printf "PRK_PL=''\n"
    printf "PRK_AM='1'\n"
    printf "PRK_AMD='1'\n"
    printf "PRK_REASON=%s\n" "$(shell_quote "$1")"
    printf "PRK_CHANGED=%s\n" "$(shell_quote "${2:-}")"
    printf "PRK_REFERENCE=%s\n" "$(shell_quote "${REF_SHA:-}")"
    printf "PRK_HEAD=%s\n" "$(shell_quote "${HEAD_SHA:-}")"
    exit 0
}

if ! cd "$REPO" 2>/dev/null; then
    emit_full "repository path not found" ""
fi

if [ -z "$REFERENCE" ]; then
    emit_full "no reference commit supplied" ""
fi

if ! printf '%s' "$REFERENCE" | grep -Eq '^[0-9a-fA-F]{40}$'; then
    emit_full "reference is not a 40-char commit SHA" ""
fi

case "$HEAD" in
    HEAD) ;;
    *)
        if ! printf '%s' "$HEAD" | grep -Eq '^[0-9a-fA-F]{40}$'; then
            emit_full "head is not HEAD or a 40-char commit SHA" ""
        fi
        ;;
esac

REF_SHA=$(git rev-parse --verify "$REFERENCE^{commit}" 2>/dev/null) || \
    emit_full "reference commit not found: $REFERENCE" ""
HEAD_SHA=$(git rev-parse --verify "$HEAD^{commit}" 2>/dev/null) || \
    emit_full "HEAD commit not found: $HEAD" ""

CHANGED=$(git diff --no-renames --name-only "$REF_SHA...$HEAD_SHA" 2>/dev/null) || \
    emit_full "git diff failed for $REFERENCE...$HEAD" ""

MODULES=$(sed -n 's:.*<module>\([^<]*\)</module>.*:\1:p' "$ROOT_POM" 2>/dev/null | \
    sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -v '^$' || true)
if [ -z "$MODULES" ]; then
    emit_full "cannot read Maven modules from $ROOT_POM" "$CHANGED"
fi

FULL=0
SELECTED=""
REASONS=""
CHANGED_LIST=""

while IFS= read -r file; do
    [ -n "$file" ] || continue
    CHANGED_LIST="${CHANGED_LIST}${CHANGED_LIST:+ }$file"

    case "$file" in
        ts-avatar-service|ts-avatar-service/*|ts-news-service|ts-news-service/*|ts-ticket-office-service|ts-ticket-office-service/*|ts-ui-dashboard|ts-ui-dashboard/*|ts-voucher-service|ts-voucher-service/*)
            REASONS="${REASONS}; non-Maven service directory ignored: $file"
            continue
            ;;
        pom.xml|./pom.xml)
            FULL=1
            REASONS="${REASONS}; root pom.xml changed"
            continue
            ;;
        .mvn/*|mvnw|mvnw.cmd|Makefile|makefile|docker-compose.yml|Dockerfile)
            FULL=1
            REASONS="${REASONS}; root build file changed: $file"
            continue
            ;;
        *.gradle|*.gradle.kts|settings.gradle|settings.gradle.kts|gradle.properties|Jenkinsfile|*/Jenkinsfile|jenkins-ci/*)
            FULL=1
            REASONS="${REASONS}; uncertain build file changed: $file"
            continue
            ;;
    esac

    matched=0
    for module in $MODULES; do
        case "$file" in
            "$module"|"$module"/*)
                SELECTED="${SELECTED}${SELECTED:+
}$module"
                REASONS="${REASONS}; $file -> $module"
                matched=1
                break
                ;;
        esac
    done

    if [ "$matched" -eq 0 ]; then
        case "$file" in
            docs/*|old-docs/*|image/*|deployment/*|*.md|*.markdown|*.rst|README|README.*|CHANGELOG|CHANGELOG.*|LICENSE|LICENSE.*|NOTICE|NOTICE.*|CONTRIBUTING|CONTRIBUTING.*)
                REASONS="${REASONS}; non-Maven file ignored: $file"
                ;;
            */pom.xml|pom.xml)
                FULL=1
                REASONS="${REASONS}; unknown Maven POM changed: $file"
                ;;
            *)
                FULL=1
                REASONS="${REASONS}; unrecognised path changed: $file"
                ;;
        esac
    fi
done <<EOF
$CHANGED
EOF

REASONS=${REASONS#; }

if [ "$FULL" -eq 1 ]; then
    emit_full "full reactor required:${REASONS}" "$CHANGED_LIST"
fi

if [ -z "$SELECTED" ]; then
    printf "PRK_MODE='none'\n"
    printf "PRK_PL=''\n"
    printf "PRK_AM='0'\n"
    printf "PRK_AMD='0'\n"
    printf "PRK_REASON=%s\n" "$(shell_quote "no Maven module or build-affecting file changed")"
    printf "PRK_CHANGED=%s\n" "$(shell_quote "$CHANGED_LIST")"
    printf "PRK_REFERENCE=%s\n" "$(shell_quote "$REF_SHA")"
    printf "PRK_HEAD=%s\n" "$(shell_quote "$HEAD_SHA")"
    exit 0
fi

SELECTED=$(printf '%s\n' "$SELECTED" | awk '!seen[$0]++')
PL=$(printf '%s\n' "$SELECTED" | paste -sd, -)

printf "PRK_MODE='modules'\n"
printf "PRK_PL=%s\n" "$(shell_quote "$PL")"
printf "PRK_AM='1'\n"
printf "PRK_AMD='1'\n"
printf "PRK_REASON=%s\n" "$(shell_quote "changed module:${REASONS}")"
printf "PRK_CHANGED=%s\n" "$(shell_quote "$CHANGED_LIST")"
printf "PRK_REFERENCE=%s\n" "$(shell_quote "$REF_SHA")"
printf "PRK_HEAD=%s\n" "$(shell_quote "$HEAD_SHA")"
