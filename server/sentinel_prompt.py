"""
Sentinel V6 prompt contract: copied verbatim, do not edit.

INSTRUCTION is extracted from
~/zgx-sentinel/training/v6/build_v6_full_curriculum_candidate_v2.py (read-only).
"""

INSTRUCTION = 'You are Sentinel, a policy-governance decision model.\n\nUse ONLY the supplied evidence.\n\nEvaluate the exact proposition in causal order:\n\n1. bind facts to the exact target\n2. determine whether a governing rule applies\n3. identify the operative rule\n4. resolve exception state when relevant\n5. resolve each material requirement as SATISFIED, FAILED, or UNRESOLVED\n6. return the decision implied by the completed state\n\nChoose exactly one:\n\nYES\nNO\nCONDITIONAL\nINSUFFICIENT\n\nINSUFFICIENT:\nThe evidence does not establish that a governing rule applies to the exact proposition.\n\nNO:\nAn applicable controlling prohibition or explicitly failed required state prevents the action.\n\nCONDITIONAL:\nApplicability is established, no controlling requirement has failed, and at least one material requirement remains unresolved.\n\nYES:\nApplicability is established and every material requirement is satisfied.\n\nReturn valid JSON only with exactly these keys:\n\ndecision\ncitations\nconditions\nrationale\n\nconditions is a complete material state ledger using:\n\nSATISFIED | requirement\nFAILED | requirement\nUNRESOLVED | requirement'

INSTRUCTION_SHA256 = "b9b445244082d27881f3794ac2fe7fa9945d4a241f276452d5f8b4f1adab1191"

LABELS = ("YES", "NO", "CONDITIONAL", "INSUFFICIENT")


def render_evidence(records):
    """records: list of evidence strings, in order. Returns E1..En block."""
    return "\n\n".join(
        f"[E{i}] {text}\nEND_RECORD" for i, text in enumerate(records, 1)
    )


def render_input(question, evidence_block, question_first=True):
    if question_first:
        return (
            "QUESTION\n========\n"
            f"{question}\n\n"
            "EVIDENCE\n========\n"
            f"{evidence_block}"
        )
    return (
        "EVIDENCE\n========\n"
        f"{evidence_block}\n\n"
        "QUESTION\n========\n"
        f"{question}"
    )


def build_messages(question, evidence_records, question_first=True):
    return [
        {"role": "system", "content": INSTRUCTION},
        {"role": "user", "content": render_input(
            question, render_evidence(evidence_records), question_first)},
    ]
