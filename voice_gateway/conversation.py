"""Multi-turn conversation engine for booking calls.

Maintains dialogue history and generates contextual next-turn responses
via ASI:One, given a translated transcript of what the receptionist said.
"""

import json

from common.asi import asi_chat

_SYSTEM_PROMPT = """\
You are a multilingual AI assistant on a phone call booking a medical \
appointment on behalf of a patient. You already introduced yourself and \
requested an appointment. Now you are in a live conversation with the \
clinic receptionist.

Patient context:
- Name: {patient_name}
- Specialty needed: {specialty}
- Insurance: {insurance}
- Preferred time: {time_pref}

Rules:
1. Answer receptionist questions naturally (DOB, insurance ID, etc.). \
   If you don't have the info, say "I'll need to check with the patient \
   and call back."
2. If asked to hold, say "Of course, I'll hold."
3. If transferred, introduce yourself again briefly.
4. When the receptionist offers a time slot, confirm it.
5. Keep responses SHORT — 1-2 sentences max. This is a phone call.
6. At the end of EVERY response, add a JSON tag on its own line:
   <status>{{"booking": "in_progress"|"booked"|"failed"|"callback_needed"}}</status>
   Use "booked" only when a specific date+time is confirmed.
   Use "failed" if they say no availability at all.
   Use "callback_needed" if you need info from the patient.
"""

_STATUS_LABELS = {"in_progress", "booked", "failed", "callback_needed"}


class ConversationState:
    """Tracks multi-turn dialogue for one call."""

    def __init__(
        self,
        patient_name: str = "the patient",
        specialty: str = "a doctor",
        insurance: str = "private",
        time_pref: str = "this week",
    ):
        self.patient_name = patient_name
        self.specialty = specialty
        self.insurance = insurance
        self.time_pref = time_pref
        self.history: list[dict] = []
        self.booking_status: str = "in_progress"
        self.turns: int = 0

    @property
    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT.format(
            patient_name=self.patient_name,
            specialty=self.specialty,
            insurance=self.insurance,
            time_pref=self.time_pref,
        )

    def next_response(self, receptionist_said: str) -> str:
        """Generate next conversational turn given what receptionist said.

        Returns the text to speak (TTS), and updates internal state.
        """
        self.turns += 1
        self.history.append({"role": "receptionist", "text": receptionist_said})

        # Build user message with full conversation history
        history_text = "\n".join(
            f"{'You' if h['role'] == 'assistant' else 'Receptionist'}: {h['text']}"
            for h in self.history
        )
        user_msg = (
            f"Conversation so far:\n{history_text}\n\n"
            "Generate your next response. Remember the <status> tag."
        )

        raw = asi_chat(self.system_prompt, user_msg, max_tokens=200)

        # Parse status tag
        spoken = raw
        if "<status>" in raw and "</status>" in raw:
            start = raw.index("<status>")
            end = raw.index("</status>") + len("</status>")
            status_json = raw[start + len("<status>") : raw.index("</status>")]
            spoken = (raw[:start] + raw[end:]).strip()
            try:
                parsed = json.loads(status_json)
                status = parsed.get("booking", "in_progress")
                if status in _STATUS_LABELS:
                    self.booking_status = status
            except (json.JSONDecodeError, AttributeError):
                pass

        self.history.append({"role": "assistant", "text": spoken})
        return spoken

    @property
    def is_terminal(self) -> bool:
        return self.booking_status in ("booked", "failed", "callback_needed")

    MAX_TURNS = 10
