import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './Markdown.css'

// Renders AI-generated text as real markdown (bold, lists, links) instead of showing the raw
// **/-/# syntax the model outputs verbatim. Only ever used for assistant/LLM output - never for
// content a user typed themselves (see call sites: PersonalAIChat.jsx's own messages and
// MessageBubble.jsx, human-to-human chat, both stay plain text on purpose).
// No rehype-raw - deliberately never renders raw HTML from model output, markdown syntax only.
const components = {
  h1: ({ children }) => <h1 className="md-heading md-h1">{children}</h1>,
  h2: ({ children }) => <h2 className="md-heading md-h2">{children}</h2>,
  h3: ({ children }) => <h3 className="md-heading md-h3">{children}</h3>,
  h4: ({ children }) => <h4 className="md-heading md-h4">{children}</h4>,
  h5: ({ children }) => <h5 className="md-heading md-h5">{children}</h5>,
  h6: ({ children }) => <h6 className="md-heading md-h6">{children}</h6>,
  p: ({ children }) => <p className="md-p">{children}</p>,
  ul: ({ children }) => <ul className="md-list">{children}</ul>,
  ol: ({ children }) => <ol className="md-list">{children}</ol>,
  li: ({ children }) => <li className="md-li">{children}</li>,
  a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
  code: ({ children }) => <code className="md-code">{children}</code>,
}

export default function Markdown({ children }) {
  return <div className="agent-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{children}</ReactMarkdown></div>
}
