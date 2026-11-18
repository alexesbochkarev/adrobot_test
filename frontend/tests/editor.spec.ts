import { expect, test, type Page } from "@playwright/test";

async function mockApi(page: Page, failPush = false) {
  let campaign = {
    campaign_id: 1,
    keitaro_id: 100,
    editor_revision: 1,
    sync_locked: false,
    publication_id: null as string | null,
    streams: [
      {
        id: 1,
        keitaro_id: 199,
        name: "Геофильтр · Австралия",
        position: 1,
        schema_kind: "redirect",
        revision: 1,
        remote_present: true,
        is_dirty: false,
        offers: [] as any[],
      },
      {
        id: 2,
        keitaro_id: 200,
        name: "Основной поток",
        position: 2,
        schema_kind: "landings",
        revision: 1,
        remote_present: true,
        is_dirty: false,
        offers: [
          {
            offer_id: 10,
            name: "Flexacil · основной лендинг",
            share: 50,
            pinned: false,
            removed: false,
            is_new: false,
          },
          {
            offer_id: 20,
            name: "Flexacil · альтернативный лендинг",
            share: 50,
            pinned: false,
            removed: false,
            is_new: false,
          },
        ],
      },
    ],
  };
  const original = structuredClone(campaign);
  const calls: { path: string; method: string; body: any; key?: string }[] = [];
  let fetched = false;
  let publication: any;
  let creation: any;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const body = request.postDataJSON();
    const key = request.headers()["idempotency-key"];
    calls.push({ path, body, key, method: request.method() });
    const respond = (data: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(data),
      });
    if (path === "/campaigns" && request.method() === "GET")
      return respond([{ id: 100, name: "test_bochkarev_campaign1" }]);
    if (path.startsWith("/reference/"))
      return respond([{ id: 1, name: "FORTESTS" }]);
    if (path === "/offers") return respond([{ id: 30, name: "Новый оффер" }]);
    if (path === "/campaigns" && request.method() === "POST") {
      creation = {
        operation_id: key,
        campaign_id: 3,
        keitaro_id: 101,
        name: body.name,
        tracking_url: "https://example.test/new",
        stream_ids: [201, 202],
      };
      return respond(creation, 201);
    }
    if (path.startsWith("/campaign-creations/"))
      return respond({
        id: creation.operation_id,
        status: "succeeded",
        phase: "completed",
        result: creation,
      });
    if (path.endsWith("/fetch")) {
      fetched = true;
      return respond(campaign);
    }
    if (path.endsWith("/streams"))
      return fetched
        ? respond(campaign)
        : respond({ detail: { code: "campaign_not_imported" } }, 404);
    const stream = campaign.streams[1];
    if (path.endsWith("/offers") && request.method() === "POST") {
      stream.offers.push({
        offer_id: 30,
        name: "Новый оффер",
        share: 33,
        pinned: false,
        removed: false,
        is_new: true,
      });
      stream.offers.forEach((x, i) => (x.share = i === 0 ? 34 : 33));
      stream.is_dirty = true;
      stream.revision++;
      return respond(stream);
    }
    if (path.endsWith("/pin") || path.endsWith("/unpin")) {
      stream.offers[0].pinned = path.endsWith("/pin");
      stream.is_dirty = true;
      stream.revision++;
      return respond(stream);
    }
    if (path.endsWith("/remove")) {
      stream.offers[1].removed = true;
      stream.offers[1].share = 0;
      stream.offers[0].share = 100;
      stream.is_dirty = true;
      stream.revision++;
      return respond(stream);
    }
    if (path.endsWith("/restore")) {
      stream.offers[1].removed = false;
      stream.offers[1].share = 50;
      stream.offers[0].share = 50;
      stream.is_dirty = true;
      stream.revision++;
      return respond(stream);
    }
    if (path.endsWith("/cancel")) {
      campaign = structuredClone(original);
      campaign.streams[1].revision = stream.revision + 1;
      return respond(campaign.streams[1]);
    }
    if (path.endsWith("/push")) {
      publication = {
        id: key,
        stream_id: 2,
        expected_revision: body.expected_revision,
        status: failPush ? "unknown" : "succeeded",
        phase: failPush ? "updating" : "completed",
        error_code: null,
        result: stream,
      };
      if (failPush) {
        campaign.sync_locked = true;
        campaign.publication_id = key;
        return respond(
          { detail: { code: "keitaro_timeout", operation_id: key } },
          502,
        );
      }
      stream.is_dirty = false;
      stream.revision++;
      return respond(publication);
    }
    if (path.endsWith("/reconcile")) {
      campaign.sync_locked = false;
      campaign.publication_id = null;
      stream.is_dirty = false;
      publication.status = "succeeded";
      publication.phase = "completed";
      return respond(publication);
    }
    if (path.startsWith("/publications/")) return respond(publication);
    return respond({ detail: { code: "unexpected_mock_request" } }, 500);
  });
  return calls;
}
async function openEditor(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /test_bochkarev_campaign1/ }).click();
  await page.getByRole("button", { name: "↻ Fetch из Keitaro" }).click();
  await expect(
    page.getByRole("heading", { name: "Основной поток" }),
  ).toBeVisible();
}
test("Fetch, pin, publish uses remote ID, current revision and idempotency key", async ({
  page,
}) => {
  const calls = await mockApi(page);
  await openEditor(page);
  await page.getByRole("button", { name: "◇ Закрепить" }).first().click();
  await expect(page.getByText("Есть изменения", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "↻ Fetch из Keitaro" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Опубликовать ↑" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Изменения опубликованы",
  );
  const push = calls.find((x) => x.path === "/streams/200/push")!;
  expect(push.body.expected_revision).toBe(2);
  expect(push.key).toMatch(/^[\da-f-]{36}$/);
  expect(calls.filter((x) => x.path.endsWith("/push"))).toHaveLength(1);
});
test("Cancel restores saved data and archived offer can be restored", async ({
  page,
}) => {
  await mockApi(page);
  await openEditor(page);
  await page
    .getByRole("button", { name: "Удалить", exact: true })
    .last()
    .click();
  await page.getByRole("button", { name: /Архив · 1/ }).click();
  await expect(page.getByRole("button", { name: "↩ Вернуть" })).toBeVisible();
  await page.getByRole("button", { name: "↩ Вернуть" }).click();
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Отменить", exact: true }).click();
  await expect(page.getByText("Есть изменения", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "↻ Fetch из Keitaro" }),
  ).toBeEnabled();
});
test("Add offer to draft", async ({ page }) => {
  await mockApi(page);
  await openEditor(page);
  await page.getByRole("button", { name: "+ Добавить оффер" }).click();
  await page
    .getByLabel("Добавляемый оффер", { exact: true })
    .selectOption("30");
  await page.getByRole("button", { name: "Добавить в поток" }).click();
  await expect(page.getByText("34%", { exact: true })).toBeVisible();
  await expect(page.getByText("#30 · новый")).toBeVisible();
});
test("Unknown push survives reload and is reconciled without second push", async ({
  page,
}) => {
  const calls = await mockApi(page, true);
  await openEditor(page);
  await page.getByRole("button", { name: "◇ Закрепить" }).first().click();
  await page.getByRole("button", { name: "Опубликовать ↑" }).click();
  await expect(
    page.getByText("Публикация требует проверки", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: /test_bochkarev_campaign1/ }).click();
  await expect(
    page.getByRole("button", { name: "Опубликовать ↑" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Сверить с Keitaro" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Публикация подтверждена",
  );
  expect(calls.filter((x) => x.path.endsWith("/push"))).toHaveLength(1);
});
test("Create campaign with required prefix and stable recoverable intent", async ({
  page,
}) => {
  const calls = await mockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "＋ Новая кампания" }).click();
  await expect(page.getByLabel("Название кампании")).toHaveValue(
    "test_bochkarev_campaign1",
  );
  await page.getByLabel("Оффер", { exact: true }).selectOption("30");
  await page
    .getByRole("button", { name: "Создать кампанию", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Кампания создана" }),
  ).toBeVisible();
  const created = calls.find(
    (x) => x.path === "/campaigns" && x.method === "POST",
  )!;
  expect(created.body.name).toMatch(/^test_bochkarev_/);
  expect(created.body.offer_id).toBe(30);
  await page.reload();
  await page.getByRole("button", { name: "＋ Новая кампания" }).click();
  await page.getByRole("button", { name: "Проверить результат" }).click();
  await expect(
    page.getByRole("heading", { name: "Кампания создана" }),
  ).toBeVisible();
  expect(
    calls.filter((x) => x.path === "/campaigns" && x.method === "POST"),
  ).toHaveLength(1);
});
test("Responsive editor has no viewport overflow", async ({ page }) => {
  await mockApi(page);
  await openEditor(page);
  await page.screenshot({
    path: "test-results/editor-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Основной поток" }),
  ).toBeVisible();
  const overflow = await page.evaluate(() =>
    [...document.querySelectorAll("body *")]
      .filter(
        (x) =>
          x.getBoundingClientRect().right > innerWidth &&
          !x.closest(".table-scroll"),
      )
      .map((x) => ({
        tag: x.tagName,
        cls: x.className,
        width: x.getBoundingClientRect().width,
      })),
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
    JSON.stringify(overflow),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/editor-mobile.png",
    fullPage: true,
  });
});
