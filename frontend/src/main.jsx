import React from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App.jsx'
import { createThemeController } from './theme.js'
import './styles.css'
import './site.css'
import './registry.css'

const theme = createThemeController(window)
createRoot(document.getElementById('root')).render(<App theme={theme} />)

if (import.meta.hot) import.meta.hot.dispose(() => theme.destroy())
