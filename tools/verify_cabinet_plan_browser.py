"""Browser smoke test against an isolated development server (requires Playwright + Edge).

Set SOP_BROWSER_TEST_PASSWORD to the test admin's password; do not point this at production.
Creates three synthetic projects. Screenshots go to ignored tests/output/cabinet-plan/.
"""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests/output/cabinet-plan"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1360, "height": 950})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(os.environ.get("SOP_BROWSER_TEST_URL", "http://127.0.0.1:8765"))
        page.get_by_role("heading", name="登录 SOP 工作台").wait_for()
        page.get_by_label("用户名", exact=True).or_(
            page.get_by_role("button", name="管理员账号登录")
        ).first.wait_for(state="visible")
        # The shared .env may enable Feishu; the local test account uses its fallback.
        if page.get_by_role("button", name="管理员账号登录").is_visible():
            page.get_by_role("button", name="管理员账号登录").click()
        page.get_by_label("用户名", exact=True).fill("admin")
        page.get_by_label("密码", exact=True).fill(
            os.environ["SOP_BROWSER_TEST_PASSWORD"]
        )
        page.locator("button[type=submit]").click()
        page.get_by_role("button", name="新建项目").click()
        dialog = page.get_by_role("dialog")
        assert dialog.get_by_text("选择业务类型", exact=True).is_visible()
        assert dialog.get_by_text("选择文档类型", exact=True).count() == 0
        assert dialog.get_by_label("项目名称", exact=True).count() == 0
        dialog.screenshot(animations="disabled", path=str(OUT / "create-business.png"))
        dialog.get_by_role("button", name="工商业柜").click()
        assert dialog.get_by_text("选择文档类型", exact=True).is_visible()
        assert dialog.get_by_label("项目名称", exact=True).count() == 0
        dialog.screenshot(animations="disabled", path=str(OUT / "create-document.png"))
        dialog.get_by_role("button", name="测试报告").click()
        dialog.get_by_role("button", name="创建并进入").click()
        dialog.get_by_text("请输入项目名称", exact=True).wait_for()
        dialog.get_by_label("项目名称", exact=True).fill("返回步骤草稿")
        dialog.get_by_role("button", name="返回选择文档").click()
        dialog.get_by_role("button", name="返回选择业务").click()
        dialog.get_by_role("button", name="升压一体机").click()
        assert dialog.get_by_role("button", name="测试报告").is_disabled()
        dialog.get_by_role("button", name="测试方案").click()
        assert (
            dialog.get_by_label("项目名称", exact=True).input_value() == "返回步骤草稿"
        )
        dialog.locator(".ant-modal-close").click()
        page.get_by_role("button", name="新建项目").click()
        assert dialog.get_by_text("选择业务类型", exact=True).is_visible()
        dialog.get_by_role("button", name="工商业柜").click()
        dialog.get_by_role("button", name="测试方案").click()
        assert dialog.get_by_label("项目名称（可选）", exact=True).input_value() == ""
        page.get_by_role("dialog").screenshot(
            animations="disabled", path=str(OUT / "create-dialog.png")
        )
        page.get_by_role("button", name="创建并进入").click()
        page.get_by_text("01 上传测试需求", exact=True).wait_for()
        page.locator("input[type=file]").set_input_files(
            str(ROOT / "templates/cabinet-test-plan/v1/input-template.xlsx")
        )
        page.get_by_text("16 个测试章节 · 1 张图片", exact=True).wait_for(timeout=60000)
        page.screenshot(
            animations="disabled", path=str(OUT / "upload-preview.png"), full_page=True
        )
        page.get_by_text("02 信息确认", exact=True).click()
        page.get_by_text("已从 Excel 读取", exact=True).wait_for()
        assert page.get_by_label("文档标题", exact=True).count() == 0
        assert page.get_by_label("编码", exact=True).count() == 0
        page.get_by_label("拟制（可选）", exact=True).fill("浏览器验证")
        page.get_by_role("button", name="保存补充信息").click()
        page.get_by_text("补充信息已保存", exact=True).wait_for()
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(
            animations="disabled", path=str(OUT / "information.png"), full_page=True
        )
        page.get_by_text("03 生成方案", exact=True).click()
        page.get_by_text("检查通过", exact=True).wait_for()
        page.get_by_role("checkbox").check()
        page.get_by_role("button", name="生成 DOCX").click()
        page.get_by_text("生成任务已提交", exact=True).wait_for()
        page.get_by_role("button", name="返回项目列表").click()
        page.get_by_role("button", name="新建项目").click()
        dialog.get_by_role("button", name="工商业柜").click()
        dialog.get_by_role("button", name="测试报告").click()
        page.get_by_label("项目名称", exact=True).fill("浏览器报告回归")
        page.get_by_role("button", name="创建并进入").click()
        page.get_by_text("04 生成文档", exact=True).wait_for()
        page.get_by_role("button", name="返回项目列表").click()
        page.get_by_role("button", name="新建项目").click()
        dialog.get_by_role("button", name="升压一体机").click()
        assert dialog.get_by_role("button", name="测试报告").is_disabled()
        dialog.get_by_role("button", name="测试方案").click()
        page.get_by_label("项目名称", exact=True).fill("浏览器升压回归")
        page.get_by_role("button", name="创建并进入").click()
        page.get_by_text("02 测试项分类表", exact=True).wait_for()
        page.get_by_role("button", name="返回项目列表").click()
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="新建项目").click()
        page.get_by_role("dialog").screenshot(
            animations="disabled", path=str(OUT / "mobile-dialog.png")
        )
        dialog.get_by_role("button", name="工商业柜").click()
        dialog.screenshot(animations="disabled", path=str(OUT / "mobile-document.png"))
        dialog.get_by_role("button", name="测试方案").click()
        dialog.get_by_label("项目名称（可选）", exact=True).wait_for()
        dialog.screenshot(animations="disabled", path=str(OUT / "mobile-details.png"))
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        assert not errors, errors
        print(
            "PASS: sequential business/document/details, back navigation, draft retention, cancel reset, three creation routes, mobile steps; no page errors"
        )
        browser.close()


if __name__ == "__main__":
    main()
