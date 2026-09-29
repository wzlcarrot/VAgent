#!/usr/bin/env bash
# CI 专用：覆盖率写 /tmp，失败时打印 last-failed 便于 Actions 日志排查。
set -euo pipefail
export COVERAGE_FILE="${COVERAGE_FILE:-/tmp/vagent-pytest.coverage}"
rm -f .coverage .coverage.*

if python -m pytest tests/ -q --junit-xml=pytest-junit.xml; then
  exit 0
fi

echo "::group::pytest last-failed"
python -m pytest tests/ --lf -q --no-cov --tb=short -r fE || true
echo "::endgroup::"
exit 1
