import { explainReasonCode } from "../utils/reasonCodes";

interface ReasonCodeBadgeProps {
  code: string;
}

/** Renders a backend reason code together with a Russian explanation.
 * Unknown codes still render safely, showing only the raw technical value. */
export function ReasonCodeBadge({ code }: ReasonCodeBadgeProps) {
  const explanation = explainReasonCode(code);
  return (
    <li className="reason-code">
      <code className="reason-code-value">{code}</code>
      <span className="reason-code-explanation">
        {explanation ?? "Неизвестный технический код причины."}
      </span>
    </li>
  );
}
