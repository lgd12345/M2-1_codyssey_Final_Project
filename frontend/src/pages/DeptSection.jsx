import React, { useState } from 'react'
import { DEPARTMENTS } from '../mock/data.js'
import { isEdited, isEditable } from '../mock/store.js'
import { Lozenge } from '../ui.jsx'

const meta = (key) => DEPARTMENTS.find((d) => d.key === key)

// Jira의 "Link work item → Create linked work item". 다른 팀이 처리할 별도 업무를 원본 요청에 연결한다.
// 승인 전에는 AI가 제안한 연결 업무(아직 전달되지 않음), 승인 후에는 생성된 연결 업무를 보여 준다.
export function DeptSection({ item, dispatch }) {
  if (item.status === '분석 중') {
    return <section className="block"><div className="block-head"><h2>연결 업무</h2></div><p className="muted">분석이 끝나면 전달할 부서와 초안이 제안됩니다. 승인 전에는 어떤 부서에도 전달되지 않습니다.</p></section>
  }
  if (item.linked.length > 0) return <Linked item={item} />
  return <Proposed item={item} dispatch={dispatch} />
}

// 승인 후의 연결 업무: 부서가 처리하는 상태·담당자·결과가 원본 요청에서 보인다.
function Linked({ item }) {
  const done = item.linked.filter((l) => l.status === '완료').length
  return (
    <section className="block" aria-labelledby="linked-title">
      <div className="block-head"><h2 id="linked-title">연결 업무 <span className="count-pill">{done}/{item.linked.length} 완료</span></h2><span className="muted small">부서의 처리 결과가 이곳에 모입니다</span></div>
      <ul className="linked">
        {item.linked.map((l) => (
          <li key={l.workKey}>
            <div className="linked-head"><span className="key">{l.workKey}</span><strong>{l.name} 팀</strong><Lozenge status={l.status} />
              <span className="muted small">{l.assignee ? `담당 ${l.assignee}` : '담당자 미지정'}</span>{l.edited && <span className="tag edited">검토 중 수정됨</span>}</div>
            <pre>{l.content}</pre>
            {l.result && <div className="work-result"><strong>처리 결과</strong><p>{l.result.summary}</p><small>작업 시간 {l.result.hours ? `${l.result.hours}시간` : '미입력'}</small></div>}
          </li>
        ))}
      </ul>
      <p className="muted small">승인한 내용만 연결 업무로 생성되며, 승인 후에는 수정할 수 없습니다.</p>
    </section>
  )
}

function Proposed({ item, dispatch }) {
  const editable = isEditable(item)
  const [collapsed, setCollapsed] = useState([])
  const toggle = (key) => setCollapsed(collapsed.includes(key) ? collapsed.filter((k) => k !== key) : [...collapsed, key])
  return (
    <section className="block" aria-labelledby="linked-title">
      <div className="block-head"><h2 id="linked-title">연결 업무 제안</h2><span className="tag pending">승인 전 · 아직 전달되지 않음</span></div>
      <p className="muted small">AI가 추천한 부서입니다. 부서를 추가하거나 제외하고 초안을 수정할 수 있습니다.{!editable && ' 반려된 건은 재분석 후에 다시 제안됩니다.'}</p>
      <ul className="proposals">
        {item.departments.map((d) => {
          const isOpen = d.selected && !collapsed.includes(d.key)
          return (
            <li key={d.key} className={d.selected ? 'on' : ''}>
              <div className="proposal-head">
                <label className="dept-check">
                  <input type="checkbox" checked={d.selected} disabled={!editable} onChange={() => dispatch({ type: 'TOGGLE_DEPT', id: item.id, key: d.key })} />
                  <span><strong>{meta(d.key).name}</strong>
                    {d.aiSelected ? <span className="tag ai">AI 추천</span> : d.selected ? <span className="tag edited">추가함</span> : null}
                    {d.aiSelected && !d.selected && <span className="tag edited">제외함</span>}
                    <small>{d.aiSelected ? d.reason : `AI 비추천 사유: ${d.reason}`}</small>
                  </span>
                </label>
                {d.selected && <button className="ghost small" aria-expanded={isOpen} onClick={() => toggle(d.key)}>{isOpen ? '초안 접기' : '초안 보기'}{isEdited(d) ? ' · 수정됨' : ''}</button>}
              </div>
              {d.selected && isOpen && (
                <div className="proposal-body">
                  <textarea className="draft" rows={6} value={d.draft} readOnly={!editable} aria-label={`${meta(d.key).name} 초안`} onChange={(e) => dispatch({ type: 'EDIT_DRAFT', id: item.id, key: d.key, text: e.target.value })} />
                  <div className="draft-foot">
                    {d.draft.trim() === '' && <span className="error small">초안이 비어 있습니다.</span>}
                    {editable && isEdited(d) && <button className="ghost small" onClick={() => dispatch({ type: 'RESET_DRAFT', id: item.id, key: d.key })}>AI 원본으로 되돌리기</button>}
                  </div>
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
