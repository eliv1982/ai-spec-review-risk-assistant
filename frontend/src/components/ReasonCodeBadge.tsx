import { labelReasonCode } from "../utils/labels";
import { explainReasonCode } from "../utils/reasonCodes";

interface ReasonCodeBadgeProps {
  code: string;
}

/** Renders a backend reason code as a short Russian label with a longer
 * explanation underneath. The raw technical code itself is never shown here
 * — it stays available only inside the "Служебные данные" JSON block; an
 * unrecognized future code still renders safely, falling back to the raw
 * value as its label and a generic explanation. */
export function ReasonCodeBadge({ code }: ReasonCodeBadgeProps) {
  const explanation = explainReasonCode(code);
  return (
    <li className="reason-code">
      <span className="reason-code-value">{labelReasonCode(code)}</span>
      <span className="reason-code-explanation">
        {explanation ?? "Неизвестный технический код причины."}
      </span>
    </li>
  );
}
