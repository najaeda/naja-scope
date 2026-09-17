# SPDX-License-Identifier: Apache-2.0
"""Native Naja design coordinates, scoped to the bridge that resolves them."""

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class DesignReference(BaseModel):
    """Same native-ID shape as Kepler MCP; no Kepler dependency or alias map."""

    model_config = ConfigDict(extra="forbid")
    session_id: StrictStr = Field(min_length=1, description="Owning Naja-Scope bridge session ID.")
    db_id: StrictInt = Field(ge=0, le=255, description="Native Naja database ID (8-bit).")
    library_id: StrictInt = Field(ge=0, le=65535, description="Native Naja library ID (16-bit).")
    design_id: StrictInt = Field(ge=0, le=4294967295, description="Native Naja design ID (32-bit).")

    def native_key(self):
        return self.db_id, self.library_id, self.design_id


def reference_from_design(session_id, design):
    from najaeda import naja

    if not isinstance(design, naja.SNLDesign):
        raise TypeError("Expected a raw naja.SNLDesign")
    identity = design.getNLID()
    return DesignReference(session_id=session_id, db_id=identity.getDBID(),
                           library_id=identity.getLibraryID(), design_id=identity.getDesignID())
