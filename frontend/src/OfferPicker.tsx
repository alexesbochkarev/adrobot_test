import { useEffect, useState } from "react";
import { api } from "./api";
import type { Item } from "./types";

export default function OfferPicker({
  value,
  onChange,
  disabled = false,
  label = "Оффер",
}: {
  value: Item | null;
  onChange: (item: Item | null) => void;
  disabled?: boolean;
  label?: string;
}) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const timer = setTimeout(() => {
      api<Item[]>(`/offers?q=${encodeURIComponent(query)}&limit=50`, {
        signal: controller.signal,
      })
        .then(setItems)
        .catch((e) => {
          if (e.name !== "AbortError") setError(e.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query]);
  return (
    <div className="picker">
      <label>
        {label}: поиск
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Название или ID оффера"
          disabled={disabled}
        />
      </label>
      <label>
        {label}
        <select
          aria-label={label}
          disabled={disabled || loading}
          value={value?.id || ""}
          onChange={(e) =>
            onChange(items.find((x) => x.id === Number(e.target.value)) || null)
          }
        >
          <option value="">{loading ? "Поиск…" : "Выберите оффер"}</option>
          {value && !items.some((x) => x.id === value.id) && (
            <option value={value.id}>
              {value.name} · #{value.id}
            </option>
          )}
          {items.map((x) => (
            <option key={x.id} value={x.id}>
              {x.name} · #{x.id}
            </option>
          ))}
        </select>
      </label>
      {error && (
        <small role="alert" className="error-text">
          {error}
        </small>
      )}
      {!loading && !error && items.length === 0 && (
        <small>Ничего не найдено. Попробуйте другой ID.</small>
      )}
    </div>
  );
}
