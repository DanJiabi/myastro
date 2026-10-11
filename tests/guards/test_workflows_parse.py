"""CI 工作流必须是可解析的 YAML，且每个 job 都有 runs-on 与 steps。

为什么需要：实测踩过——步骤名里写了一个冒号+空格
（`name: Runtime smoke (network): …`）就让**整个 ci.yml 解析失败**，
GitHub 上表现为"运行创建了但没有任何 job、日志取不到"，
本地 `pytest` 与 `ruff` 全绿、完全无感。这类错误必须在推之前抓住。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted(Path(".github/workflows").glob("*.yml"))


@pytest.mark.cap("ci.config")
def test_workflow_dir_is_not_empty():
    assert WORKFLOWS, "没有找到任何工作流文件（路径变了？）"


@pytest.mark.cap("ci.config")
@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_is_parseable_and_well_formed(path):
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), f"{path.name}: 顶层不是映射"
    assert data.get("jobs"), f"{path.name}: 没有 jobs"
    # 触发条件：on 在 YAML 里会被解析成布尔 True，两种键名都要接受
    assert ("on" in data) or (True in data), f"{path.name}: 缺少 on（触发条件）"
    for name, job in data["jobs"].items():
        assert "runs-on" in job, f"{path.name}: job {name} 缺少 runs-on"
        assert job.get("steps"), f"{path.name}: job {name} 没有 steps"
        for step in job["steps"]:
            assert ("run" in step) or ("uses" in step), \
                f"{path.name}: job {name} 有既无 run 也无 uses 的步骤"
