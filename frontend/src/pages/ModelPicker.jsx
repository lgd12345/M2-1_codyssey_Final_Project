import React, { useEffect, useId, useRef, useState } from 'react'

// A single editable select: input and arrow share one field and one popup.
export function ModelPicker({ models, value, onChange, disabled: busy = false }) {
  const id = useId()
  const root = useRef(null)
  const input = useRef(null)
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const selected = models.find(model => model.id === value)
  const options = models.filter(model => model.machine.toLowerCase().includes(text.trim().toLowerCase()))
  const disabled = busy || !models.length

  useEffect(() => {
    const outside = event => { if (!root.current?.contains(event.target)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [])

  function choose(model) {
    onChange(model.id)
    setText('')
    setOpen(false)
    setActive(-1)
    input.current?.focus()
  }

  function keyDown(event) {
    if (event.key === 'Escape' && open) {
      event.preventDefault(); event.stopPropagation(); setOpen(false)
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault(); setOpen(true)
      const direction = event.key === 'ArrowDown' ? 1 : -1
      const next = options.length ? (active + direction + options.length) % options.length : -1
      setActive(next)
      requestAnimationFrame(() => document.getElementById(`${id}-option-${next}`)?.scrollIntoView({ block: 'nearest' }))
    } else if (event.key === 'Enter' && open) {
      event.preventDefault()
      if (active >= 0 && options[active]) choose(options[active])
    } else if (event.key === 'Tab') setOpen(false)
  }

  return <div className="model-picker" ref={root}>
    <label htmlFor={id}>기종 *</label>
    <div className="model-picker-field">
      <input id={id} ref={input} role="combobox" autoComplete="off" placeholder="기종 선택"
        value={selected ? selected.machine : text} disabled={disabled} aria-required="true"
        aria-expanded={open} aria-controls={`${id}-list`} aria-autocomplete="list"
        aria-activedescendant={open && active >= 0 ? `${id}-option-${active}` : undefined}
        onClick={() => { setOpen(true); input.current?.select() }} onKeyDown={keyDown}
        onChange={event => { onChange(''); setText(event.target.value); setActive(-1); setOpen(true) }} />
      <button type="button" aria-label="기종 목록" aria-expanded={open} aria-controls={`${id}-list`}
        disabled={disabled} onClick={() => { setOpen(!open); setActive(-1); input.current?.focus() }}>▾</button>
    </div>
    {open && !disabled && <div className="model-picker-popup">
      <ul id={`${id}-list`} role="listbox" aria-label="기종 목록">
        {options.map((model, index) => <li key={model.id} id={`${id}-option-${index}`} role="option"
          aria-selected={model.id === value} className={index === active ? 'active' : ''}
          onPointerDown={event => event.preventDefault()} onClick={() => choose(model)}>{model.machine}</li>)}
      </ul>
      {!options.length && <p role="status">일치하는 기종이 없습니다.</p>}
    </div>}
  </div>
}
