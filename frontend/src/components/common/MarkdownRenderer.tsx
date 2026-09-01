import React, { useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { CopyOutlined, CheckOutlined } from '@ant-design/icons';
import { Button, Tooltip } from 'antd';
import type { Components } from 'react-markdown';

interface MarkdownRendererProps {
  content: string;
}

const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({ content }) => {
  const [copiedIndex, setCopiedIndex] = React.useState<number | null>(null);

  const handleCopy = useCallback(
    async (code: string, index: number) => {
      try {
        await navigator.clipboard.writeText(code);
        setCopiedIndex(index);
        setTimeout(() => setCopiedIndex(null), 2000);
      } catch {
        // Fallback copy method
        const textarea = document.createElement('textarea');
        textarea.value = code;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        setCopiedIndex(index);
        setTimeout(() => setCopiedIndex(null), 2000);
      }
    },
    []
  );

  const components: Components = {
    code({ className, children }) {
      const match = /language-(\w+)/.exec(className ?? '');
      const codeString = String(children).replace(/\n$/, '');
      // Use a unique key per code block
      const codeBlockKey = React.useId();

      if (match) {
        return (
          <div style={{ position: 'relative', margin: '16px 0', borderRadius: 6, maxWidth: '100%', overflowX: 'auto' }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '8px 12px',
                background: '#282c34',
                color: '#abb2bf',
                fontSize: 12,
              }}
            >
              <span>{match[1]}</span>
              <Tooltip title={copiedIndex === parseInt(codeBlockKey) ? 'Copied!' : 'Copy code'}>
                <Button
                  type="text"
                  size="small"
                  icon={
                    copiedIndex === parseInt(codeBlockKey) ? (
                      <CheckOutlined style={{ color: '#52c41a' }} />
                    ) : (
                      <CopyOutlined style={{ color: '#abb2bf' }} />
                    )
                  }
                  onClick={() => handleCopy(codeString, parseInt(codeBlockKey))}
                  style={{ color: '#abb2bf' }}
                />
              </Tooltip>
            </div>
            <SyntaxHighlighter
              style={oneDark}
              language={match[1]}
              PreTag="div"
              customStyle={{ margin: 0, borderRadius: '0 0 6px 6px', maxWidth: '100%' }}
            >
              {codeString}
            </SyntaxHighlighter>
          </div>
        );
      }

      return (
        <code
          style={{
            background: '#f5f5f5',
            padding: '2px 6px',
            borderRadius: 4,
            fontSize: '0.9em',
            color: 'inherit',
          }}
        >
          {children}
        </code>
      );
    },
    pre({ children }) {
      return <>{children}</>;
    },
  };

  return (
    <div className="markdown-renderer">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
};

export default React.memo(MarkdownRenderer);
