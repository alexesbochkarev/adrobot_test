import { useState } from "react";
import OfferPicker from "./OfferPicker";
import type { Item, Offer, Stream } from "./types";

type Props = {
  stream: Stream;
  disabled: boolean;
  onAction: (
    stream: Stream,
    action: string,
    offerId?: number,
    share?: number,
  ) => void;
};
function OfferRow({
  offer,
  stream,
  disabled,
  onAction,
}: Props & { offer: Offer }) {
  const [share, setShare] = useState(String(offer.share));
  const valid =
    /^\d+$/.test(share) && Number(share) >= 0 && Number(share) <= 100;
  return (
    <tr className={offer.removed ? "archived" : ""}>
      <td>
        <div className="offer-title">{offer.name}</div>
        <small>
          #{offer.offer_id}
          {offer.is_new ? " · новый" : ""}
        </small>
      </td>
      <td>
        <div className="share">
          <strong>{offer.share}%</strong>
          <div className="share-track">
            <span style={{ width: `${offer.share}%` }} />
          </div>
        </div>
      </td>
      <td>
        {offer.removed ? (
          <span className="muted">В архиве</span>
        ) : (
          <form
            className="pin-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (valid) onAction(stream, "pin", offer.offer_id, Number(share));
            }}
          >
            <input
              aria-label={`Доля оффера ${offer.offer_id}`}
              type="number"
              min="0"
              max="100"
              step="1"
              value={share}
              onChange={(e) => setShare(e.target.value)}
              disabled={disabled}
            />
            <button
              title="Закрепить долю"
              disabled={disabled || !valid}
              type="submit"
            >
              {offer.pinned ? "◆ Закреплено" : "◇ Закрепить"}
            </button>
            {offer.pinned && (
              <button
                type="button"
                aria-label={`Снять закрепление ${offer.offer_id}`}
                disabled={disabled}
                onClick={() => onAction(stream, "unpin", offer.offer_id)}
              >
                Снять
              </button>
            )}
          </form>
        )}
      </td>
      <td className="row-action">
        <button
          disabled={
            disabled ||
            (!offer.removed &&
              stream.offers.filter((x) => !x.removed).length === 1)
          }
          onClick={() =>
            onAction(
              stream,
              offer.removed ? "restore" : "remove",
              offer.offer_id,
            )
          }
        >
          {offer.removed ? "↩ Вернуть" : "Удалить"}
        </button>
      </td>
    </tr>
  );
}
export default function StreamCard(props: Props) {
  const { stream, disabled, onAction } = props;
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<Item | null>(null);
  const [showArchive, setShowArchive] = useState(false);
  const editable = stream.schema_kind === "landings" && stream.remote_present;
  const active = stream.offers.filter((x) => !x.removed);
  const archived = stream.offers.filter((x) => x.removed);
  return (
    <section
      className={`stream-card ${stream.is_dirty ? "dirty" : ""}`}
      aria-label={`Поток ${stream.name}`}
    >
      <header className="stream-header">
        <div className="stream-heading">
          <span className="flow-number">
            {String(stream.position).padStart(2, "0")}
          </span>
          <div>
            <h3>{stream.name}</h3>
            <small>
              Поток #{stream.keitaro_id} ·{" "}
              {editable
                ? `${active.length} офферов`
                : stream.schema_kind === "redirect"
                  ? "Перенаправление"
                  : "Другой маршрут"}
            </small>
          </div>
        </div>
        <span className={`badge ${stream.is_dirty ? "amber" : ""}`}>
          {!stream.remote_present
            ? "Недоступен"
            : stream.is_dirty
              ? "Есть изменения"
              : "Синхронизирован"}
        </span>
      </header>
      {!editable ? (
        <div className="flow-info">
          {stream.remote_present
            ? "Настройки этого маршрута управляются в Keitaro."
            : "Поток больше не найден в Keitaro. Редактирование недоступно."}
        </div>
      ) : (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Оффер</th>
                  <th>Доля трафика</th>
                  <th>Закрепление</th>
                  <th>
                    <span className="sr-only">Действия</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {active.map((x) => (
                  <OfferRow
                    {...props}
                    key={`${stream.revision}-${x.offer_id}`}
                    offer={x}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {!active.length && (
            <p className="empty-inline">
              В этом потоке пока нет активных офферов.
            </p>
          )}
          {archived.length > 0 && (
            <div className="archive">
              <button
                className="text-button"
                onClick={() => setShowArchive(!showArchive)}
                aria-expanded={showArchive}
              >
                {showArchive ? "▾" : "▸"} Архив · {archived.length}
              </button>
              {showArchive && (
                <div className="table-scroll">
                  <table>
                    <tbody>
                      {archived.map((x) => (
                        <OfferRow
                          {...props}
                          key={`${stream.revision}-${x.offer_id}`}
                          offer={x}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
          {adding && (
            <div className="add-offer">
              <OfferPicker
                label="Добавляемый оффер"
                value={selected}
                onChange={setSelected}
                disabled={disabled}
              />
              <button
                disabled={disabled || !selected}
                onClick={() => {
                  if (selected) onAction(stream, "add", selected.id);
                }}
              >
                Добавить в поток
              </button>
            </div>
          )}
          <footer className="stream-footer">
            <button
              className="text-button"
              disabled={disabled}
              onClick={() => setAdding(!adding)}
            >
              {adding ? "− Скрыть поиск" : "+ Добавить оффер"}
            </button>
            <span className="total">
              Сумма{" "}
              <strong>{active.reduce((sum, x) => sum + x.share, 0)}%</strong>
            </span>
            {stream.is_dirty && (
              <div className="actions">
                <button
                  disabled={disabled}
                  onClick={() => {
                    if (
                      window.confirm(
                        "Отменить все неопубликованные изменения этого потока?",
                      )
                    )
                      onAction(stream, "cancel");
                  }}
                >
                  Отменить
                </button>
                <button
                  className="primary"
                  disabled={disabled}
                  onClick={() => onAction(stream, "push")}
                >
                  Опубликовать ↑
                </button>
              </div>
            )}
          </footer>
        </>
      )}
    </section>
  );
}
