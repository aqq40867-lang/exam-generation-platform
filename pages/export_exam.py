import io
import zipfile
from datetime import datetime

from nicegui import ui, app, run

from database import (
    load_questions,
    get_question_parts,
    add_exam,
    add_question_to_exam,
)
from latex_export import build_latex, compile_latex_to_pdf, LatexCompileError


def export_exam_page():
    """Build a new exam paper by selecting questions from the question
    bank, giving each one a mark value *for this exam*, and exporting the
    result as a PDF (rendered from a LaTeX template)."""

    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    username = app.storage.user["username"]

    all_questions = load_questions()
    questions = [q for q in all_questions if q.get("Created by") == username]
    questions.sort(key=lambda q: q["id"])
    for display_id, q in enumerate(questions, start=1):
        q["display_id"] = display_id

    with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-4"):

        ui.link("← Back to Question Bank", "/questions").classes("text-sm")
        ui.label("Export Exam Paper").classes("text-2xl font-bold")
        ui.label(
            "Select questions from your question bank, set the marks each "
            "one is worth in this exam, then generate a PDF once the "
            "selected marks add up to the full marks total."
        ).classes("text-sm text-grey-600")

        if not questions:
            ui.label("You don't have any questions yet. Create some first.").classes("text-grey-600")
            ui.button("Create New Question", on_click=lambda: ui.navigate.to("/questions/new"))
            return

        # -- Exam settings -----------------------------------------------
        with ui.card().classes("w-full p-4"):
            with ui.row().classes("w-full items-end gap-4"):
                exam_name = ui.input("Exam Name", value="New Exam").classes("w-64")
                total_marks_input = ui.number(
                    "Full Marks (target total)", value=100, min=1
                ).classes("w-56")
            exam_description = ui.input("Description (optional)").classes("w-full")

            ui.label("Export as").classes("font-semibold mt-2")
            export_mode = ui.radio(
                {
                    "official": "Official paper — for printing, in the exam hall "
                                 "(blank answer space + continuation pages at the end)",
                    "example": "Example + Answers — for revision, not printed "
                                "(a practice paper plus a matching answer version, "
                                "so students can self-mark)",
                },
                value="official",
            ).props("inline")

        # -- Selection state -----------------------------------------------
        selected_ids: set = set()
        row_widgets = {}  # question_id -> {"marks_input": ..., "row": ..., "checkbox": ...}

        status_label = ui.label().classes("text-lg font-bold")
        generate_btn = None  # assigned below, referenced by refresh_status()
        generate_tooltip = None  # assigned below, explains why the button is disabled
        download_tex_btn = None

        def selected_total() -> int:
            total = 0
            for qid in selected_ids:
                widget = row_widgets.get(qid)
                if widget:
                    total += int(widget["marks_input"].value or 0)
            return total

        def disabled_reason(count: int, total: int, target: int) -> str:
            """Human-readable reason the Generate button is currently
            disabled, or '' if it isn't. Shown as a tooltip on the button
            (a disabled button in Quasar has pointer-events disabled, so
            the tooltip is attached to a wrapper div around it instead --
            see how generate_btn is created below)."""
            if count == 0:
                return "Select at least one question first."
            if total < target:
                return (
                    f"Selected marks ({total}) are {target - total} short of "
                    f"the full marks total ({target}). Select more questions "
                    f"or increase their marks in this exam."
                )
            if total > target:
                return (
                    f"Selected marks ({total}) are {total - target} over the "
                    f"full marks total ({target}). Remove a question or lower "
                    f"some marks in this exam."
                )
            return ""

        def refresh_status():
            total = selected_total()
            target = int(total_marks_input.value or 0)
            count = len(selected_ids)
            status_label.text = f"Selected: {count} question(s) — {total} / {target} marks"

            ok = count > 0 and total == target
            if ok:
                status_label.classes(replace="text-lg font-bold text-green-700")
            else:
                status_label.classes(replace="text-lg font-bold text-red-600")

            if generate_btn is not None:
                generate_btn.enable() if ok else generate_btn.disable()
            if generate_tooltip is not None:
                reason = disabled_reason(count, total, target)
                generate_tooltip.set_text(reason)
                generate_tooltip.set_visibility(bool(reason))
            if download_tex_btn is not None:
                download_tex_btn.enable() if count > 0 else download_tex_btn.disable()

        total_marks_input.on_value_change(lambda e: refresh_status())

        # -- Search filter ---------------------------------------------------
        search_input = ui.input("Search by question text or module").classes("w-full")

        # -- Question checklist -----------------------------------------------
        with ui.card().classes("w-full p-0"):
            with ui.row().classes(
                "w-full items-center font-bold border-b px-3 py-2 bg-grey-100"
            ):
                ui.label("").classes("w-10")
                ui.label("ID").classes("w-10")
                ui.label("Question").classes("flex-grow")
                ui.label("Module").classes("w-28")
                ui.label("Default").classes("w-20")
                ui.label("Marks in exam").classes("w-36")

            list_container = ui.column().classes("w-full gap-0")

            def build_rows():
                list_container.clear()
                row_widgets.clear()
                with list_container:
                    for q in questions:
                        qid = q["id"]
                        default_marks = int(q.get("Marks") or 0)

                        with ui.row().classes(
                            "w-full items-center border-b px-3 py-2"
                        ) as row:
                            checkbox = ui.checkbox().classes("w-10")
                            ui.label(str(q["display_id"])).classes("w-10")
                            ui.label(q.get("Question") or "").classes(
                                "flex-grow truncate"
                            )
                            ui.label(q.get("Module") or "—").classes("w-28")
                            ui.label(str(default_marks)).classes("w-20")
                            marks_input = ui.number(
                                value=default_marks, min=0
                            ).classes("w-36")
                            marks_input.disable()

                            def on_toggle(e, qid=qid, marks_input=marks_input):
                                if e.value:
                                    selected_ids.add(qid)
                                    marks_input.enable()
                                else:
                                    selected_ids.discard(qid)
                                    marks_input.disable()
                                refresh_status()

                            checkbox.on_value_change(on_toggle)
                            marks_input.on_value_change(lambda e: refresh_status())

                            row_widgets[qid] = {
                                "checkbox": checkbox,
                                "marks_input": marks_input,
                                "row": row,
                                "question": q,
                            }

            build_rows()

            def apply_search():
                term = (search_input.value or "").strip().lower()
                for q in questions:
                    widget = row_widgets.get(q["id"])
                    if not widget:
                        continue
                    haystack = f"{q.get('Question') or ''} {q.get('Module') or ''}".lower()
                    widget["row"].set_visibility(term in haystack)

            search_input.on_value_change(lambda e: apply_search())

        refresh_status()

        # -- Generate ------------------------------------------------------
        with ui.row().classes("w-full items-center gap-4 mt-2"):
            # The button itself is wrapped in a plain div. A disabled Quasar
            # button has pointer-events disabled, so it never sees mouse
            # hover and a tooltip attached directly to it would never show.
            # The wrapper div isn't disabled, so hovering anywhere over the
            # button's footprint still reaches it and triggers the tooltip.
            with ui.element("div") as generate_wrapper:
                generate_btn = ui.button("Generate & Download", color="primary")
            generate_tooltip = (
                ui.tooltip("")
                .props(f'target="#{generate_wrapper.html_id}"')
                .style("font-size: 14px")
            )
            download_tex_btn = ui.button("Download LaTeX Source (.tex)", color="secondary")
            generate_btn.disable()
            download_tex_btn.disable()

        # Populate the tooltip's initial text/visibility now that
        # generate_tooltip exists (the first refresh_status() call above
        # ran before this button block, when it was still None).
        refresh_status()

        def gather_selected():
            """Return (name, description, total, questions_with_marks) built
            from the current selection, in display order."""
            name = (exam_name.value or "New Exam").strip()
            description = (exam_description.value or "").strip()
            total = int(total_marks_input.value or 0)

            questions_with_marks = []
            for q in questions:
                if q["id"] not in selected_ids:
                    continue
                widget = row_widgets[q["id"]]
                marks = int(widget["marks_input"].value or 0)
                parts = get_question_parts(q["id"])
                questions_with_marks.append((q, marks, parts))

            return name, description, total, questions_with_marks

        def _safe_filename(name: str) -> str:
            return "".join(c for c in name if c.isalnum() or c in " _-").strip() or "exam"

        def _zip_bytes(files: dict) -> bytes:
            """files: {filename: bytes/str}. Returns the zip archive's bytes."""
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for filename, content in files.items():
                    zf.writestr(filename, content)
            return buf.getvalue()

        async def on_download_tex():
            if not selected_ids:
                ui.notify("Select at least one question first.", color="warning")
                return
            name, description, total, questions_with_marks = gather_selected()
            safe_name = _safe_filename(name)

            if export_mode.value == "official":
                tex_source, assets = build_latex(name, description, total, questions_with_marks, mode="official")
                # Bundle any embedded images alongside the .tex source so
                # someone compiling this elsewhere (e.g. Overleaf) has
                # everything \includegraphics references, not just the
                # source text.
                files = {f"{safe_name}.tex": tex_source, **assets}
                if assets:
                    ui.download(_zip_bytes(files), filename=f"{safe_name}_tex.zip")
                else:
                    ui.download(tex_source.encode("utf-8"), filename=f"{safe_name}.tex")
            else:
                example_tex, example_assets = build_latex(name, description, total, questions_with_marks, mode="example")
                solutions_tex, solutions_assets = build_latex(name, description, total, questions_with_marks, mode="solutions")
                zip_bytes = _zip_bytes({
                    f"{safe_name}_example.tex": example_tex,
                    f"{safe_name}_solutions.tex": solutions_tex,
                    **example_assets,
                    **solutions_assets,
                })
                ui.download(zip_bytes, filename=f"{safe_name}_revision_pack_tex.zip")

        async def on_generate():
            total = selected_total()
            target = int(total_marks_input.value or 0)
            if not selected_ids:
                ui.notify("Select at least one question first.", color="warning")
                return
            if total != target:
                ui.notify(
                    f"Selected marks ({total}) must equal the full marks total ({target}).",
                    color="negative",
                )
                return

            name, description, total, questions_with_marks = gather_selected()
            mode = export_mode.value
            safe_name = _safe_filename(name)

            generate_btn.disable()
            generate_btn.props("loading")
            try:
                try:
                    if mode == "official":
                        tex_source, assets = build_latex(name, description, total, questions_with_marks, mode="official")
                        pdf_bytes = await run.io_bound(compile_latex_to_pdf, tex_source, 60, assets)
                    else:
                        # "Example + Answers": two separate documents -- a
                        # practice paper (blank answer space, no answers)
                        # and a matching solutions version (shaded answer
                        # boxes inline) -- zipped together into one download
                        # so a student gets both with a single click but can
                        # look at the example before checking the solutions.
                        example_tex, example_assets = build_latex(name, description, total, questions_with_marks, mode="example")
                        solutions_tex, solutions_assets = build_latex(name, description, total, questions_with_marks, mode="solutions")
                        example_pdf = await run.io_bound(compile_latex_to_pdf, example_tex, 60, example_assets)
                        solutions_pdf = await run.io_bound(compile_latex_to_pdf, solutions_tex, 60, solutions_assets)
                except LatexCompileError as exc:
                    ui.notify(str(exc), color="negative", multi_line=True, close_button=True)
                    return

                # Persist the composed exam so it's recorded in the exam bank.
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                exam_id = add_exam({
                    "Name": name,
                    "Description": description,
                    "Total marks": target,
                    "Status": "Exported" if mode == "official" else "Revision Pack",
                    "Created by": username,
                    "Created at": now,
                })
                for order, (q, marks, _parts) in enumerate(questions_with_marks):
                    add_question_to_exam(exam_id, q["id"], order=order, marks_override=marks)

                if mode == "official":
                    ui.download(pdf_bytes, filename=f"{safe_name}.pdf")
                    ui.notify("Exam paper generated.", color="positive")
                else:
                    zip_bytes = _zip_bytes({
                        f"{safe_name}_example.pdf": example_pdf,
                        f"{safe_name}_solutions.pdf": solutions_pdf,
                    })
                    ui.download(zip_bytes, filename=f"{safe_name}_revision_pack.zip")
                    ui.notify("Example + Answers pack generated.", color="positive")
            finally:
                generate_btn.props(remove="loading")
                refresh_status()

        generate_btn.on_click(on_generate)
        download_tex_btn.on_click(on_download_tex)
