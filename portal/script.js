function qs(id){return document.getElementById(id)}
const form=qs('ttsForm')
const result=qs('result'), player=qs('player'), statusBox=qs('status'), link=qs('downloadLink'), voicesOut=qs('voicesOut')

qs('engine').addEventListener('change', ()=>{
  const eng = qs('engine').value
  qs('piperOpts').open = (eng === 'piper')
  qs('exprOpts').open  = (eng !== 'piper')
})

bindSSMLButtons()

form.addEventListener('submit', synthesize)
qs('btnVoices').addEventListener('click', listVoices)
qs('btnSavePreset').addEventListener('click', savePreset)

async function synthesize(e){
  e.preventDefault()
  showResult(); setBusy(true); status('Sintetizando...')
  try{
    const body = buildBody()
    if(body.engine === 'piper' && qs('savePreset').checked && qs('userId').value && qs('preset').value){
      await doSavePreset(qs('userId').value, qs('preset').value)
    }
    const res = await fetch('/api/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    await handleAudioResponse(res, player, link, body.fmt)
    status('Listo ✅')
  }catch(err){ status('❌ '+(err?.message||err)); console.error(err) } finally { setBusy(false) }
}

async function listVoices(){
  showResult(); status('Consultando voces (Piper)...')
  try{
    const res = await fetch('/api/voices')
    if(!res.ok) throw new Error(await res.text())
    voicesOut.classList.remove('hidden')
    voicesOut.textContent = JSON.stringify(await res.json(), null, 2)
    status('Voces instaladas ✅')
  }catch(err){ status('❌ '+(err?.message||err)); voicesOut.textContent='' }
}

async function savePreset(){
  const user = qs('userId').value.trim(), preset = qs('preset').value.trim()
  if(!user || !preset) return alert('Necesitas User ID y un preset.')
  try{ await doSavePreset(user, preset); alert('Preset guardado para '+user) }
  catch(err){ alert('Error guardando preset: '+(err?.message||err)) }
}

async function doSavePreset(user, preset){
  const url = `/api/prefs/preset?user_id=${encodeURIComponent(user)}&preset=${encodeURIComponent(preset)}`
  const res = await fetch(url, { method:'POST' })
  if(!res.ok) throw new Error(await res.text())
}

function buildBody(){
  const engine = qs('engine').value
  const common = {
    engine,
    text: qs('text').value,
    fmt: qs('fmt').value
  }
  if(engine === 'piper'){
    return Object.assign(common, {
      voice: val(qs('voice').value),
      preset: val(qs('preset').value),
      user_id: val(qs('userId').value),
      length_scale: num(qs('lengthScale').value, 1.0),
      noise_scale: num(qs('noiseScale').value, 0.667),
      sentence_silence: num(qs('sentenceSilence').value, 0.2),
      onnx_url: val(qs('onnxUrl').value),
      json_url: val(qs('jsonUrl').value),
      postprocess: qs('postprocess').checked
    })
  } else {
    return Object.assign(common, {
      x_voice: val(qs('xVoice').value),
      style: val(qs('xStyle').value),
      lang: val(qs('xLang').value) || 'es',
      speed: num(qs('xSpeed').value, 1.0),
      temperature: num(qs('xTemp').value, 0.8)
    })
  }
}

// ----- helpers UI -----
function showResult(){ result.classList.remove('hidden'); voicesOut.classList.add('hidden') }
function setBusy(b){ qs('btnSpeak').disabled=b }
function status(s){ statusBox.textContent=s }
function val(s){ s=String(s||'').trim(); return s || undefined }
function num(v,d){ const n=parseFloat(v); return Number.isFinite(n)?n:d }
async function handleAudioResponse(res, audioEl, dlEl, fmt){
  if(!res.ok) throw new Error(await res.text())
  const blob = await res.blob(); const url = URL.createObjectURL(blob)
  audioEl.src = url; audioEl.play().catch(()=>{})
  dlEl.href = url; dlEl.download = `tts_output.${fmt==='wav'?'wav':'mp3'}`
}

// ----- SSML-light buttons -----
function bindSSMLButtons(){
  const t = qs('text')
  doclick('btnBreak', ()=> insertAtCursor(t, '<break time="400ms"> '))
  doclick('btnEmph', ()=> wrapSelection(t, '<emphasis>', '</emphasis>'))
  doclick('btnProsodySlow', ()=> wrapSelection(t, '<prosody rate="slow">', '</prosody>'))
  doclick('btnProsodyFast', ()=> wrapSelection(t, '<prosody rate="fast">', '</prosody>'))
}
function doclick(id, fn){ const b=document.getElementById(id); if(b) b.addEventListener('click', fn) }
function insertAtCursor(el, str){
  const [start, end] = [el.selectionStart ?? el.value.length, el.selectionEnd ?? el.value.length]
  el.value = el.value.slice(0,start) + str + el.value.slice(end)
  el.focus(); el.selectionStart = el.selectionEnd = start + str.length
}
function wrapSelection(el, left, right){
  const [start, end] = [el.selectionStart ?? 0, el.selectionEnd ?? 0]
  const sel = el.value.slice(start, end) || 'texto'
  el.value = el.value.slice(0,start) + left + sel + right + el.value.slice(end)
  el.focus(); el.selectionStart = start + left.length; el.selectionEnd = el.selectionStart + sel.length
}
