interface ErrorBannerProps {
  message: string;
  title?: string;
}

/** Accessible, user-facing error message. Never renders raw technical details. */
export function ErrorBanner({ message, title = "Ошибка" }: ErrorBannerProps) {
  return (
    <div className="banner banner-error" role="alert">
      <strong className="banner-title">{title}</strong>
      <p className="banner-text">{message}</p>
    </div>
  );
}
