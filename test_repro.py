import asyncio
from nicegui import ui, app
from nicegui.testing import User
from nicegui.testing.user_interaction import UserInteraction

def interact(user, element):
    return UserInteraction(user, {element}, None)

async def test_bug(user: User):
    await user.open("/login")
    await user.should_see(content="Exam Platform Login")

    inputs = list(user.find(ui.input).elements)
    inputs.sort(key=lambda e: e.id)
    username_input, password_input = inputs[0], inputs[1]
    interact(user, username_input).type("yan")
    interact(user, password_input).type("password123")

    login_btn = next(b for b in user.find(ui.button).elements if b.text == "Login")
    interact(user, login_btn).click()
    await asyncio.sleep(0.2)

    await user.should_see(content="Welcome, yan")
    print("Logged in, on questions page now")

    table = list(user.find(ui.table).elements)[0]
    print("Table rows:", table.rows)
    print("Table selected before:", table.selected)

    row1 = next(r for r in table.rows if r["id"] == 1)
    row2 = next(r for r in table.rows if r["id"] == 2)

    interact(user, table).trigger("selection", args={"added": True, "rows": [row1], "keys": [1]})
    await asyncio.sleep(0.1)
    interact(user, table).trigger("selection", args={"added": True, "rows": [row2], "keys": [2]})
    await asyncio.sleep(0.1)

    print("Table selected after:", table.selected)
    with user.client:
        print("app.storage.user exam_selection:", app.storage.user.get("exam_selection"))

    await user.open("/exams/export")
    await asyncio.sleep(0.2)
    try:
        await user.should_see(content="No questions selected yet")
        print("BUG REPRODUCED: export page shows 'No questions selected yet'")
    except AssertionError:
        print("Export page shows selected questions (no bug)")
    assert False  # force pytest to print output
