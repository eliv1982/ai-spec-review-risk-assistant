import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <main className="page">
      <div className="container">
        <h1>Страница не найдена</h1>
        <p className="lead">Запрошенный адрес не существует. Проверьте ссылку или вернитесь на главную.</p>
        <p>
          <Link to="/" className="button button-primary">
            Вернуться к созданию документа
          </Link>
        </p>
      </div>
    </main>
  );
}
