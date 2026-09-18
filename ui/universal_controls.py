from __future__ import annotations

import streamlit as st

from core.config import DatasetRole
from strategies.base_strategy import ParameterType, StrategyDescriptor


def render_status_badge(descriptor: StrategyDescriptor) -> None:
    st.caption(f"Strategy status: **{descriptor.metadata.status.value}** · {descriptor.metadata.category}")


def render_dynamic_parameters(descriptor: StrategyDescriptor) -> dict[str, object]:
    values: dict[str, object] = {}
    if not descriptor.parameters:
        st.caption("This strategy exposes no Phase-1 editable strategy parameters.")
        return values
    for spec in descriptor.parameters:
        disabled = spec.frozen
        label = spec.name.replace("_", " ").title()
        help_text = spec.description or ("Frozen validated parameter." if disabled else None)
        if spec.parameter_type.value in {"integer"}:
            values[spec.name] = st.number_input(
                label, value=int(spec.default), min_value=spec.minimum, max_value=spec.maximum,
                step=int(spec.step or 1), disabled=disabled, help=help_text,
            )
        elif spec.parameter_type.value in {"boolean"}:
            values[spec.name] = st.checkbox(label, value=bool(spec.default), disabled=disabled, help=help_text)
        elif spec.choices:
            values[spec.name] = st.selectbox(label, spec.choices,
                                             index=spec.choices.index(spec.default),
                                             disabled=disabled, help=help_text)
        else:
            kwargs = {"value": float(spec.default), "disabled": disabled, "help": help_text}
            if spec.minimum is not None:
                kwargs["min_value"] = float(spec.minimum)
            if spec.maximum is not None:
                kwargs["max_value"] = float(spec.maximum)
            if spec.step is not None:
                kwargs["step"] = float(spec.step)
            values[spec.name] = st.number_input(label, **kwargs)
    return values


def dataset_role_selectbox() -> DatasetRole:
    value = st.selectbox("Dataset Role", [role.value for role in DatasetRole])
    return DatasetRole(value)
