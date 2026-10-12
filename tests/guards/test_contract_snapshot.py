"""契约快照守卫：代码与 `docs/contract-snapshot.json` 必须一致。

为什么需要：0.2.0 → 0.3.5 的复盘里，对外契约其实零漂移，但**我是用正则数引号字符串
量出来的，数是错的**（详见 `docs/change-policy.md` §1.1）。手工统计（靠人、靠我）会错，
所以让机器守着：任何契约变化都必须显式重新生成快照并在
`docs/contract-changelog.md` 里写一行理由。

本守卫**必须能红**——变异验证（三种，见提交信息）：
① 加一个门面导出；② 改一个 CLI 选项名；③ 在 `_MIGRATIONS` 加一个版本。
"""
from __future__ import annotations

import pytest

from myastro import contract


@pytest.mark.cap("design.contract")
def test_contract_snapshot_is_current():
    issues = contract.problems()
    assert not issues, (
        f"契约快照与代码不一致（{len(issues)} 处）：\n"
        + "\n".join(issues)
        + "\n\n若这是**有意的**契约变更：\n"
          "  1) 运行 `myastro contract-snapshot` 重新生成；\n"
          "  2) 在 `docs/contract-changelog.md` 追加一行（契约点/变更/理由/兼容性）；\n"
          "否则请修正代码。"
    )


@pytest.mark.cap("design.contract")
def test_snapshot_is_the_generated_bytes():
    """快照必须是生成器的**逐字节**结果——防止手工编辑/手工修数。"""
    path = contract.snapshot_path()
    assert path.read_text() == contract.dumps(), (
        f"{path} 不是生成物的字节结果（被手工改过？）——请用 "
        f"`myastro contract-snapshot` 重新生成")
