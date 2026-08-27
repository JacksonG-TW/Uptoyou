"""Ticket 14 — the engine's write half: one transaction stores the roll, or nothing does.

**D15's reconciliation is the reason this module exists.** The caller folded, drew, and names
the weights it drew against; this module re-folds the records it is about to store and refuses
the whole write if the two disagree. Recomputing with the same `fold` is not circular: what is
being checked is that the *records* — the only thing the panel and item 14 will ever see —
reproduce the weights the draw actually used. A contribution the caller folded but forgot to
hand over, a weight edited after the fold, a place with records and no weight: each lands as a
raised error before anything is written.

**The engine fills the pins (D43).** A contributor returns an effect and a sentence; which
exact reading row was read is known only to the loader, so the pin types here are the loader's
to construct and a contributor never sees them.

**The close rides in the same transaction (D14, D53).** Setting the round closed fires 0008's
erasure trigger, so authorship dies at the same instant the result becomes durable. The caller
owns the session and the commit; this module only writes and raises.

**A zero-weight winner is refused (D45).** A veto that the draw then ignores is not a veto.
The check is cheap and the failure it catches — a draw implemented over the wrong column, or
over no column — is exactly the kind that looks fine on a happy path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from upto.engine.fold import Contribution, fold


@dataclass(frozen=True)
class ForecastPin:
    """The forecast reading actually read — forecast_reading's whole primary key."""

    publication_id: int
    township_code: str
    element: str
    measure: str
    slot_start: datetime


@dataclass(frozen=True)
class ObservationPin:
    """The observation reading actually read — observation_reading's whole primary key."""

    publication_id: int
    station_id: str
    element: str
    observed_at: datetime


@dataclass(frozen=True)
class PreferencePin:
    """The preference **version** actually read — one id, and that is the whole point of it.

    D24/D25: a round records which version of a preference it applied, so a version some round
    used cannot be deleted (`ON DELETE RESTRICT`) and a re-read of history reproduces the number.
    A preference has no composite key to pin because, unlike a reading, it is one row.
    """

    preference_id: int


@dataclass(frozen=True)
class PinnedContribution:
    """A contribution plus what only the engine knows: the pin and the visibility."""

    contribution: Contribution
    pin: ForecastPin | ObservationPin | PreferencePin
    reason_visibility: str
    member_id: int | None = None


class ReconciliationError(Exception):
    """D15: the records do not reproduce the weights the draw used. Nothing was written."""


async def write_roll(
    session,
    round_id: int,
    pinned: list[PinnedContribution],
    weights: dict[int, Decimal],
    winning_place_id: int,
    dice: tuple[int, int],
    forecast_baseline: "ForecastPin | None" = None,
) -> None:
    """Store contributions, weights, the dice and the close. Raises before writing on any mismatch."""
    if not (1 <= dice[0] <= 6 and 1 <= dice[1] <= 6):
        raise ReconciliationError(f"{dice} is not a roll of two dice (D72)")
    pool = set(
        (
            await session.execute(
                text("select place_id from proposal where round_id = :r"), {"r": round_id}
            )
        )
        .scalars()
        .all()
    )
    if set(weights) != pool:
        raise ReconciliationError(
            f"weights name places {sorted(set(weights))} but round {round_id}'s pool is "
            f"{sorted(pool)} — every pooled place carries a weight, and only pooled places do"
        )
    if winning_place_id not in pool:
        raise ReconciliationError(f"winner {winning_place_id} is not in round {round_id}'s pool")
    if weights[winning_place_id] == 0:
        raise ReconciliationError(
            f"winner {winning_place_id} carries weight 0 — a veto the draw ignored (D45)"
        )

    # D15: re-fold the records about to be stored; they must reproduce the drawn weights.
    by_place: dict[int, list[Contribution]] = {place_id: [] for place_id in pool}
    for p in pinned:
        if p.contribution.place_id not in by_place:
            raise ReconciliationError(
                f"contribution {p.contribution.id} lands on place {p.contribution.place_id}, "
                f"which is not in round {round_id}'s pool"
            )
        by_place[p.contribution.place_id].append(p.contribution)
    for place_id, contributions in by_place.items():
        replayed = fold(place_id, contributions).weight
        if replayed != weights[place_id]:
            raise ReconciliationError(
                f"place {place_id}: the records fold to {replayed} but the draw used "
                f"{weights[place_id]} — the stored story would not be the story (D15)"
            )

    for p in pinned:
        c, pin = p.contribution, p.pin
        params = {
            "r": round_id,
            "p": c.place_id,
            "channel": c.channel,
            "contributor": c.contributor,
            "effect": c.effect,
            "reason": c.reason,
            "vis": p.reason_visibility,
            "member": p.member_id,
        }
        if isinstance(pin, ForecastPin):
            pin_columns = (
                "forecast_publication_id, forecast_township_code, forecast_element, "
                "forecast_measure, forecast_slot_start"
            )
            params |= {
                "s1": pin.publication_id,
                "s2": pin.township_code,
                "s3": pin.element,
                "s4": pin.measure,
                "s5": pin.slot_start,
            }
            pin_values = ":s1, :s2, :s3, :s4, :s5"
        elif isinstance(pin, ObservationPin):
            pin_columns = (
                "observation_publication_id, observation_station_id, "
                "observation_element, observation_observed_at"
            )
            params |= {
                "s1": pin.publication_id,
                "s2": pin.station_id,
                "s3": pin.element,
                "s4": pin.observed_at,
            }
            pin_values = ":s1, :s2, :s3, :s4"
        elif isinstance(pin, PreferencePin):
            pin_columns = "preference_id"
            params |= {"s1": pin.preference_id}
            pin_values = ":s1"
        else:
            # **Named rather than defaulted.** This used to be a bare `else` that treated anything
            # not a `ForecastPin` as an observation, which was true while there were two kinds and
            # became a silent wrong answer the moment a third arrived — it would have written a
            # preference's id into `observation_publication_id`. A new pin now fails loudly here
            # instead, which is D24's whole argument (a wrong row cannot be told from a right one
            # afterwards) applied to the writer rather than to the schema.
            raise TypeError(
                "unknown pin type {} — a contribution must name which row it was computed from, "
                "and adding a source means adding a branch here and a column in a "
                "migration".format(type(pin).__name__)
            )
        await session.execute(
            text(
                "insert into weight_contribution "
                "(round_id, place_id, channel, contributor, effect, reason, "
                f" reason_visibility, member_id, {pin_columns}) "
                f"values (:r, :p, :channel, :contributor, :effect, :reason, :vis, :member, "
                f" {pin_values})"
            ),
            params,
        )

    # **A12 / revision 0030: the reading every rain factor in this round was measured against.**
    # It has no contribution to hang from — the place standing on the pool's lowest 降雨機率
    # produces no record (D43) — so D24's pin lives in its own row. Written here, in the same
    # transaction as the contributions and before the close, so a round cannot end up holding
    # factors whose baseline is not named.
    #
    # **`None` means no comparison happened**, and no row is written: a pool with no reference
    # place, no township, or a publication carrying none of them. A round where every township
    # held the same number *does* write one — a comparison happened and found no difference, which
    # is a different fact from no comparison at all (D112).
    #
    # **Defaulted to `None` so the two callers that never load weather do not have to say so**, and
    # deliberately not defaulted anywhere the loader is involved: `rounds.py` passes what the walk
    # produced, whatever that is.
    if forecast_baseline is not None:
        await session.execute(
            text(
                "insert into round_forecast_baseline "
                "(round_id, publication_id, township_code, element, measure, slot_start) "
                "values (:r, :p, :t, :e, :m, :s)"
            ),
            {
                "r": round_id,
                "p": forecast_baseline.publication_id,
                "t": forecast_baseline.township_code,
                "e": forecast_baseline.element,
                "m": forecast_baseline.measure,
                "s": forecast_baseline.slot_start,
            },
        )

    for place_id, weight in weights.items():
        await session.execute(
            text("update proposal set weight = :w where round_id = :r and place_id = :p"),
            {"w": weight, "r": round_id, "p": place_id},
        )

    # The close: fires 0008's erasure trigger in this same transaction (D14).
    closed = (
        await session.execute(
            text(
                "update round set status = 'closed', closed_at = now(), "
                "winning_place_id = :w, die1 = :d1, die2 = :d2 "
                "where id = :r and status = 'open' returning id"
            ),
            {"w": winning_place_id, "r": round_id, "d1": dice[0], "d2": dice[1]},
        )
    ).scalar_one_or_none()
    if closed is None:
        raise ReconciliationError(f"round {round_id} is not open — a roll closes a round once")
