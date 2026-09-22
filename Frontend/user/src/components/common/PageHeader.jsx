export default function PageHeader({ eyebrow, title, description, action }) {
  return (
    <div className="page-heading d-flex flex-wrap justify-content-between align-items-end gap-3">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p className="mb-0">{description}</p>}
      </div>
      {action}
    </div>
  )
}
