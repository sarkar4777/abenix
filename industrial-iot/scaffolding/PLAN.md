# Industrial-IoT extension — three RWE-inspired apps end-to-end

Three new tabs added on top of the existing Pump/ColdChain/Architecture set. Each is a complete vertical: dedicated UI, agents, code asset(s) where useful, ML model where useful, KB collection seeded with curated assets, sample data + images pulled from the open web.

---

## Tab 1 — ValueEdge (engineering & EPC copilot)
**Folder:** `industrial-iot/scaffolding/valueedge/`
**UI:** `industrial-iot/web/src/app/tabs/ValueEdgeTab.tsx`
**API namespace:** `/api/industrial-iot/valueedge/*`
**Agents (4):**
- `iot_valueedge_scenario_configurator` — generates N design scenarios from site constraints + RWE standards
- `iot_valueedge_ve_optimizer` — ranks value-engineering opportunities (CapEx vs CO2 vs risk)
- `iot_valueedge_compliance_checker` — validates against ontology cardinalities + standards (NEC/IEC/IEEE)
- `iot_valueedge_rfi_drafter` — drafts compliance RFIs with cited evidence
**Code asset:** `valueedge_cost_calculator` (Python) — computes CapEx + CO2 + IRR per scenario
**KB:** `rwe-valueedge-design-standards` (NEC, IEC 61400, IEEE 1547, RWE-style EPC standards excerpts)
**Scaffolding assets:** wind-farm site photos, electrical SLD diagrams, BOM excerpts, IFB sample
**User journey:** "I have a 200 MW offshore wind site, generate 3 designs" → see ranked scenarios → drill into 1 → see VE opps + RFI drafts.

---

## Tab 2 — FieldEdge (wind-farm maintenance + scheduling)
**Folder:** `industrial-iot/scaffolding/fieldedge/`
**UI:** `industrial-iot/web/src/app/tabs/FieldEdgeTab.tsx`
**API namespace:** `/api/industrial-iot/fieldedge/*`
**Agents (4):**
- `iot_fieldedge_troubleshoot_assistant` — voice-or-text query → repair steps grounded in OEM manuals + fleet history
- `iot_fieldedge_fleet_history_searcher` — finds similar past WOs across the fleet
- `iot_fieldedge_schedule_optimizer` — weekly schedule for blade-repair / crane-team work
- `iot_fieldedge_closeout_documenter` — voice transcript → structured WO record
**Code asset:** `fieldedge_or_tools_scheduler` (Python OR-tools) — constraint-based schedule solver
**ML model:** `fieldedge_failure_classifier` (sklearn pickled) — turbine failure-class predictor (small synthetic-trained)
**KB:** `rwe-fieldedge-oem-manuals` (Vestas/Siemens-Gamesa public maintenance manual excerpts, common WO patterns)
**Scaffolding assets:** turbine photos, blade-erosion images, technician QR-scan sample
**User journey:** scan turbine QR → "blade leading-edge erosion, what now?" → grounded answer → voice close-out → schedule auto-adjusts.

---

## Tab 3 — BedROCC (operations control room)
**Folder:** `industrial-iot/scaffolding/bedrocc/`
**UI:** `industrial-iot/web/src/app/tabs/BedRoccTab.tsx`
**API namespace:** `/api/industrial-iot/bedrocc/*`
**Agents (4):**
- `iot_bedrocc_alarm_classifier` — severity + root-cause hypothesis from a SCADA alarm
- `iot_bedrocc_noise_filter` — suppresses correlated cascade alarms
- `iot_bedrocc_safe_reset_advisor` — proposes safe remote reset with two-step confirm gate
- `iot_bedrocc_shift_reporter` — drafts the EOD shift report from the day's alarms
**Code asset:** none (uses tool registry only)
**KB:** `rwe-bedrocc-sop-procedures` (sample SOPs, alarm playbooks, safety procedures)
**Scaffolding assets:** SCADA control-room screenshot mock-ups, sample alarm streams
**User journey:** alarm fires → triage card with severity + ROI + confidence → one-click "approve safe reset" → audit log → EOD shift report.

---

## Shared wiring
- `industrial-iot/web/src/app/page.tsx` — register 3 new tabs
- `packages/db/seeds/agents/iot_*` — register 12 new agent YAMLs
- `packages/db/seeds/kb/industrial-iot-knowledge.yaml` — extend with 3 new collections
- `packages/db/seeds/seed_agents.py` (or wherever the registration lives) — auto-loads any new YAMLs
- `industrial-iot/api/main.py` — extend pipeline catalogue with 3 new entries

## Build cadence
1. Each tab built by its own subagent in parallel (isolated files).
2. After all three return: integrator pass — wire `page.tsx`, run typecheck, build image, deploy.
3. Verify each tab loads + golden-path agent call returns sensible output on Azure.
