"""Settle operations for worker runs.

A "settle run" is the lifecycle between a worker producing artifacts and those
artifacts being trusted enough to merge into the target binding. The state
machine in this package enforces the transitions:

    proposed -> selected -> applied
                          \\-> released
                          \\-> discarded

Terminal states (``applied``, ``released``, ``discarded``) are absorbing.
Persistence to Dhara happens BEFORE any filesystem side-effect (see the
``persist_before_*`` helpers), so a process crash cannot leave a binding
uncommitted but Dhara state updated.

Public surface:

* :class:`SettleState` — enum of legal states.
* :class:`SettleAction` — enum of legal actions (select/apply/release/discard).
* :class:`SettleRunRecord` — durable record persisted under ``settle/v1/{run_ref}``.
* :func:`transition` — validate and apply a state change, returning the new record.
* :func:`legal_next` — list legal actions from a given state (for UI / tooltips).
* :class:`SettleTransitionError` — raised for illegal transitions or missing runs.
* :class:`SettlePersistenceError` — raised when Dhara write fails pre-write.
"""
