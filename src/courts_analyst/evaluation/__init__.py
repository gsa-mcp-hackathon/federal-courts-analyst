"""Evaluation harness: question bank, deterministic scorers, answerers, runner.

The benchmark lives in ``eval/questions/*.yaml`` (one file per suite). This
package loads and validates it (:mod:`.bank`), scores answers without an LLM
judge (:mod:`.scoring`), defines the :class:`~.answerers.Answerer` protocol
that every system under test implements, and runs a suite end to end
(:mod:`.runner`, CLI ``courts-eval``). See ``eval/README.md``.
"""
