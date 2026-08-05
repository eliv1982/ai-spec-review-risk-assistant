interface LoadingIndicatorProps {
  message: string;
}

export function LoadingIndicator({ message }: LoadingIndicatorProps) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}
