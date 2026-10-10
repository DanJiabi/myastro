"""门面契约：第三方视角的公开 API 测试。

本层规则（由 tests/guards/test_capability_map.py 强制）：
- 不得 import myastro 内部模块；需要隔离系统副作用时用 monkeypatch 的
  **字符串路径**（不是 import）。
- 覆盖目标：`ma.__all__` 每个导出至少被引用一次（守卫自动检查）。

覆盖面：四类错误异常、执行器隐身规则、参数校验、第三方扩展点、
索引/巡检/检索/覆盖率、批次与重试、定时任务、等待语义。
"""
from __future__ import annotations

import pytest


class TestFacadeE0:
    # 其余成员已拆分至：guards/test_boundaries.py、kernel/test_jobs.py

    @pytest.mark.cap("acquire.query")
    def test_query_resolves_without_submit(self, env):
        import myastro as ma

        plan = ma.query("legacy", brick="0001m002")
        assert "executor" not in plan  # 执行器对第三方隐身
        assert plan["url"].endswith("tractor-0001m002.fits")
        assert ma.status() == []  # 计划不产生作业（公开 API 验证）

    @pytest.mark.cap("facade.api")
    def test_param_error_mapping(self, env):
        import myastro as ma

        with pytest.raises(ma.ParamError):
            ma.fetch("tess", bogus=1)
        with pytest.raises(ma.ParamError):
            ma.fetch("no-such-source")

    @pytest.mark.cap("facade.api")
    def test_coerce_and_choices(self, env):
        """类型强转与 choices 校验走公开 API（第三方看到的即契约）。"""
        import myastro as ma

        plan = ma.query("tess", target="X", sector="20")  # str→int
        assert plan["params"]["sector"] == 20
        assert plan["params"]["cadence"] == "2m"
        with pytest.raises(ma.ParamError):
            ma.query("tess", target="X", cadence="5m")


class TestFacadeSurface:
    """`ma.__all__` 逐项契约（守卫保证无遗漏）。"""

    @pytest.mark.cap("source.registry")
    def test_sources_and_describe(self, env):
        import myastro as ma

        rows = ma.sources()
        names = {r["name"] for r in rows}
        assert {"tess", "legacy", "ztf"} <= names
        tess = ma.describe("tess")
        assert tess["name"] == "tess"
        assert any(f["name"] == "target" for f in tess["fields"])
        assert tess["orderable"] is True

    @pytest.mark.cap("source.registry")
    def test_describe_unknown_raises(self, env):
        """describe 对未知源不得静默返回 None。"""
        import myastro as ma

        with pytest.raises((StopIteration, KeyError, ma.ParamError)):
            ma.describe("no-such-source")

    @pytest.mark.cap("manage.index")
    def test_index_lifecycle(self, env):
        """索引三件套：清单 / 构建（builder 型无需网络）/ 检索。"""
        import myastro as ma

        rows = {r["name"]: r for r in ma.index_list()}
        assert "ztf-fields" in rows and "legacy-bricks" in rows
        assert rows["ztf-fields"]["built"] is False      # 干净环境未构建

        path = ma.index_update("ztf-fields")
        assert path.endswith("ztf-fields.parquet")
        assert ma.index_search("ztf-fields", "673", limit=3) == ["673"]
        assert {r["name"]: r["built"] for r in ma.index_list()}["ztf-fields"]

    @pytest.mark.cap("manage.coverage")
    def test_coverage(self, env):
        import myastro as ma

        ma.index_update("ztf-fields")
        r = ma.coverage("ztf-fields")
        assert r["total"] == 1776 and r["local"] == 0 and r["pct"] == 0.0
        with pytest.raises(ma.NotFoundError):
            ma.coverage("no-such-index")

    @pytest.mark.cap("manage.integrity")
    def test_audit_search_delete_surface(self, env):
        import myastro as ma

        report = ma.audit()
        assert {"total", "ok", "missing", "corrupt"} <= set(report)
        assert ma.search(source="nope") == []            # 过滤生效
        assert isinstance(ma.delete([]), dict)           # 空删除是合法输入

    @pytest.mark.cap("acquire.schedule")
    def test_schedule_list_and_install(self, env, monkeypatch, tmp_path):
        """清单 + 安装（字符串路径隔离到 tmp，绝不碰真 launchd）。"""
        import myastro as ma

        rows = ma.schedule_list()
        assert {r["task"] for r in rows} >= {"health", "index-weekly"}

        monkeypatch.setattr("myastro.io.schedule.LAUNCHD_DIR",
                            tmp_path / "LaunchAgents")
        monkeypatch.setattr("myastro.io.schedule.subprocess.run",
                            lambda *a, **k: None)
        written = ma.schedule_install("health")
        assert written.endswith("com.myastro.health.plist")
        with pytest.raises(ma.NotFoundError):
            ma.schedule_install("no-such-task")


class TestFacadeErrorTaxonomy:
    """四类异常都必须能从公开 API 触发（第三方靠它们分流处置）。"""

    @pytest.mark.cap("acquire.retry")
    def test_not_found(self, env):
        import myastro as ma

        with pytest.raises(ma.NotFoundError):
            ma.retry(999999)
        with pytest.raises(ma.NotFoundError):
            ma.wait(999999)
        with pytest.raises(ma.NotFoundError):
            ma.retry_batch("no-such-batch")

    @pytest.mark.cap("acquire.retry")
    def test_state_error_on_non_retryable(self, env, monkeypatch):
        """排队中的作业不 force 重试 → StateError（状态不允许）。"""
        import myastro as ma

        monkeypatch.setattr("myastro.io.jobs.runner._start_aria2_job",
                            lambda *a, **k: None)
        # 守护进程在线 ⇒ 新排队的作业是"健康运行中"，不 force 不可重试
        monkeypatch.setattr("myastro.io.aria2.ping", lambda: True)
        out = ma.batch("legacy", [{"brick": "0001m002"}])
        with pytest.raises(ma.StateError):
            ma.retry(out["job_ids"][0], force=False)

    @pytest.mark.cap("acquire.fetch")
    def test_network_error(self, env, monkeypatch):
        """网络层失败映射为 NetworkError（源实现抛 ConnectionError）。"""
        import myastro as ma

        def boom(*a, **k):
            raise ConnectionError("模拟断网")

        monkeypatch.setattr("myastro.io.sources.tess._download_lc", boom)
        with pytest.raises(ma.NetworkError):
            ma.fetch("tess", target="X", sector=20)

    @pytest.mark.cap("acquire.batch")
    def test_batch_and_status_roundtrip(self, env, monkeypatch):
        """批次提交后可按 batch_id 查看（第三方视角的批次闭环）。"""
        import myastro as ma

        monkeypatch.setattr("myastro.io.jobs.runner._start_aria2_job",
                            lambda *a, **k: None)
        out = ma.batch("legacy", [{"brick": "0001m002"},
                                  {"brick": "0001m005"}])
        rows = ma.status(batch_id=out["batch_id"])
        assert len(rows) == 2 and out["n"] == 2
        assert all(r["batch_id"] == out["batch_id"] for r in rows)

class TestFacadePrefill:
    """预填充：作业 spec → 表单值（build_spec 的逆映射）。"""

    @pytest.mark.cap("source.registry")
    def test_prefill_descriptor_job(self, env, monkeypatch):
        import myastro as ma

        monkeypatch.setattr("myastro.io.jobs.runner._start_aria2_job",
                            lambda *a, **k: None)
        out = ma.batch("legacy", [{"brick": "0001m002"}])
        pf = ma.prefill(out["job_ids"][0])
        assert pf["mode"] == "descriptor" and pf["source"] == "legacy"
        assert pf["params"] == {"brick": "0001m002"}

    @pytest.mark.cap("source.registry")
    def test_prefill_missing_job(self, env):
        import myastro as ma

        with pytest.raises(ma.NotFoundError):
            ma.prefill(999999)


class TestFacadeCoordinateSearch:
    """门面只负责把 near/radius_deg 转发下去（语义由内核层测试证明）。

    本层不允许 import 内核（守卫强制），所以这里只做参数接入的轻断言；
    锥内/锥外、排序、跨 0° 见 tests/kernel/test_search.py::TestConeSearch。
    """

    @pytest.mark.cap("manage.search")
    def test_near_parameters_are_accepted(self, env):
        import myastro as ma

        assert ma.search(near=(10.0, 0.0), radius_deg=0.5) == []   # 空账本
        assert ma.search(near=(10.0, 0.0)) == []                   # 默认半径


class TestQueryBoundaryContract:
    """门面契约：越界参数必须是 ParamError（第三方据此分流）。"""

    @pytest.mark.cap("facade.api")
    @pytest.mark.parametrize("kwargs", [
        {"near": (150.0, 2.0), "radius_deg": -1},
        {"near": (150.0, 95.0)},
        {"limit": 0},
        {"since": "乱码"},
    ])
    def test_boundary_violations_raise_param_error(self, env, kwargs):
        import myastro as ma
        with pytest.raises(ma.ParamError):     # 错误分类是门面公开面
            ma.search(**kwargs)


class TestDoctorAndBackupContract:
    """门面契约：环境自检与账本备份/恢复（0.2.0 新增的四个导出）。"""

    @pytest.mark.cap("manage.doctor")
    def test_doctor_returns_checks(self, env):
        import myastro as ma
        checks = ma.doctor()
        assert checks and {"name", "status", "detail", "fix"} <= set(checks[0])
        assert {c["status"] for c in checks} <= {"ok", "warn", "fail"}

    @pytest.mark.cap("manage.backup")
    def test_backup_errors_are_param_errors(self, env, tmp_path):
        import myastro as ma
        with pytest.raises(ma.ParamError):
            ma.restore(tmp_path / "not-a-backup")
