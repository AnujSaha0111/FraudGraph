import type { ApiError } from "../api/client";

export function ErrorState({ error }: { error: ApiError }) {
  let title: string;
  let explanation: string;
  switch (error.status) {
    case 404:
      title = "Not found";
      explanation =
        "This transaction ID does not exist in the dataset. IEEE-CIS IDs are large integers (e.g. 2987004).";
      break;
    case 422:
      title = "Coverage limitation";
      explanation =
        "The transaction exists in the raw data but cannot be scored or investigated: production feature coverage is unavailable (IEEE-CIS identity information covers only ~24% of transactions). This is a real dataset limitation, not an error in your input.";
      break;
    case 503:
      title = "Service unavailable";
      explanation =
        "The underlying storage/service is unavailable. The API is reachable but its dependencies are not ready.";
      break;
    case 0:
      title = "Network failure";
      explanation =
        "The FraudGraph API could not be reached. Start it with: uvicorn app.main:app --reload";
      break;
    default:
      title = `Error ${error.status}`;
      explanation = "";
  }
  return (
    <div className={`error-state ${error.status === 0 ? "error-network" : ""}`} role="alert">
      <h3>{title}</h3>
      {explanation && <p className="muted">{explanation}</p>}
      <pre className="error-detail" data-testid="error-detail">
        {error.detail}
      </pre>
    </div>
  );
}
