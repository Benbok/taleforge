import { beforeEach, describe, expect, it } from "vitest";
import { useDraft } from "./draft";
import { cardActions } from "./entities";

beforeEach(() => {
  localStorage.clear();
  useDraft.setState(useDraft.getInitialState(), true);
  useDraft.getState().load("campaign");
});

describe("намерение из карточки объекта", () => {
  it("сохраняет конкретную цель осмотра после перезагрузки", () => {
    const action = cardActions("landmark", "Старое пепелище", "pyre")[0];
    useDraft.getState().insert(action.text, action.action);
    useDraft.getState().load("campaign");
    expect(useDraft.getState().text).toBe("Осматриваю: Старое пепелище");
    expect(useDraft.getState().quick).toEqual([{ verb: "inspect", target_id: "pyre" }]);
  });

  it("ручное уточнение сохраняет текст и передаёт всю изменённую заявку парсеру", () => {
    const draft = useDraft.getState();
    draft.insert("Осматриваю: Старое пепелище", { verb: "inspect", target_id: "pyre" });
    draft.setText("Осматриваю: Старое пепелище на предмет ценных вещей");
    expect(useDraft.getState().quick).toBeNull();
    expect(useDraft.getState().text).toContain("на предмет ценных вещей");
    draft.load("campaign");
    expect(useDraft.getState().quick).toBeNull();
  });

  it("не заменяет уже набранную заявку одним действием из карточки", () => {
    const draft = useDraft.getState();
    draft.setText("Сначала зажигаю факел.");
    draft.insert("Осматриваю: Старое пепелище", { verb: "inspect", target_id: "pyre" });
    expect(useDraft.getState().text).toBe("Сначала зажигаю факел. Осматриваю: Старое пепелище");
    expect(useDraft.getState().quick).toBeNull();
  });

  it("не переносит выбранную цель в другую кампанию", () => {
    useDraft.getState().insert("Подбираю: Зелье", { verb: "pick_up", target_id: "potion" });
    useDraft.getState().load("other-campaign");
    expect(useDraft.getState().quick).toBeNull();
    expect(useDraft.getState().text).toBe("");
  });
});
