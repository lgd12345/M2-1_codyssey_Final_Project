import React, { useState } from 'react'
import { evidencePageUrl } from '../domain/actions.js'
import { Modal } from '../ui.jsx'

// Opens the original manual page behind a citation, as an image rendered from the original PDF on the server.
// What may be opened is decided by the server; a refusal or a missing file is shown instead of an empty frame.
export function SourcePageButton({ itemId, evidenceId, title }) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState('loading') // loading | ready | failed
  return (
    <>
      <button className="ghost small" onClick={() => { setState('loading'); setOpen(true) }}>원본 페이지 보기</button>
      {open && (
        <Modal title={`원본 페이지 · ${title}`} onClose={() => setOpen(false)}>
          {state === 'loading' && <p className="muted" role="status">원본 페이지를 불러오는 중…</p>}
          {state === 'failed' && <p className="error" role="alert">원본 PDF 페이지를 열 수 없습니다. 관리자에게 문의해 주세요.</p>}
          <img className="source-page" src={evidencePageUrl(itemId, evidenceId)} alt={`${title} 원본 페이지`} hidden={state !== 'ready'}
            onLoad={() => setState('ready')} onError={() => setState('failed')} />
          {state === 'ready' && <p className="muted small">원본 PDF를 이미지로 변환한 페이지입니다.</p>}
        </Modal>
      )}
    </>
  )
}
