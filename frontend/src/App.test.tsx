import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App — навигация", () => {
  beforeEach(() => {
    // /reviews and /audit fetch on mount; navigation assertions don't depend
    // on that data, so a never-resolving fetch keeps them harmlessly loading
    // instead of hitting a real (undefined-in-jsdom) network call.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("ссылки навигации ведут на точные маршруты", () => {
    renderAt("/");

    expect(screen.getByRole("link", { name: "Проверить документ" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "История проверок" })).toHaveAttribute("href", "/reviews");
    expect(screen.getByRole("link", { name: "Журнал аудита" })).toHaveAttribute("href", "/audit");
  });

  it("активный маршрут помечен aria-current=page", () => {
    renderAt("/reviews");

    expect(screen.getByRole("link", { name: "История проверок" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Проверить документ" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Журнал аудита" })).not.toHaveAttribute("aria-current");
  });

  it("/reviews: отрисован уникальный заголовок витрины, экран создания документа не отрисован, активна ссылка «История проверок»", () => {
    renderAt("/reviews");

    expect(screen.getByRole("heading", { name: "История проверок", level: 1 })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /ии-рецензент требований и технических заданий/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/название документа/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "История проверок" })).toHaveAttribute("aria-current", "page");
  });

  it("/audit: отрисован уникальный заголовок журнала аудита, витрина проверок не отрисована, активна ссылка «Журнал аудита»", () => {
    renderAt("/audit");

    expect(screen.getByRole("heading", { name: "Журнал аудита", level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "История проверок", level: 1 })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Идентификатор документа")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Журнал аудита" })).toHaveAttribute("aria-current", "page");
  });

  it("/reviews/:reviewId: отрисован уникальный экран результата (loading), активна ссылка «История проверок»", () => {
    renderAt("/reviews/some-review-id");

    // The fetch never resolves in this test, so the page is committed to its
    // loading state — still a real, review-detail-specific render, not the
    // dashboard or create-document screen.
    expect(screen.getByText(/загружаем результат проверки/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "История проверок", level: 1 })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /ии-рецензент требований и технических заданий/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "История проверок" })).toHaveAttribute("aria-current", "page");
  });

  it("неизвестный маршрут по-прежнему показывает русскую 404-страницу, основной экран не отрисован", () => {
    renderAt("/something/unknown");

    expect(screen.getByRole("heading", { name: /страница не найдена/i })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /ии-рецензент требований и технических заданий/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/название документа/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "История проверок", level: 1 })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Журнал аудита", level: 1 })).not.toBeInTheDocument();
  });

  it("главная страница по-прежнему показывает форму создания документа", () => {
    renderAt("/");

    expect(
      screen.getByRole("heading", { name: /ии-рецензент требований и технических заданий/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/название документа/i)).toBeInTheDocument();
  });
});
