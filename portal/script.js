function qs(id){return document.getElementById(id)}
const form=qs('ttsForm'), result=document.getElementById('result'), player=qs('player')
const statusBox=qs('status'), link=qs('downloadLink'), voicesBtn=qs('btnVoices'), voicesOut=qs('voicesOut')
const btnSpeak=qs('btnSpeak')

async function synthesize(e){
  e.preventDefault()
  btnSpeak.disabled=true; statusBox.textContent='Sintetizando...'; result.classList.remove('hidden'); voicesOut.classList.add('hidden')
  try{
    const body={
      text: qs('text').value,
      voice: qs('voice').value || undefined,
      fmt: qs('fmt').value,
      preset: qs('preset').value || undefined,
      length_scale: parseFloat(qs('lengthScale').value || '1.0'),
      noise_scale: parseFloat(qs('noiseScale').value || '0.667'),
      sentence_silence: parseFloat(qs('sentenceSilence').value || '0.2'),
      onnx_url: qs('onnxUrl').value || undefined,
      json_url: qs('jsonUrl').value || undefined
    }
    // mismo origen: /api/speak lo proxyea Nginx al contenedor tts-api
    const res=await fetch('/api/speak',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    if(!res.ok){ const t=await res.text(); throw new Error('Error '+res.status+': '+t)}
    const blob=await res.blob()
    const url=URL.createObjectURL(blob)
    player.src=url; player.play().catch(()=>{})
    const ext=(qs('fmt').value==='wav'?'wav':'mp3')
    link.href=url; link.download='tts_output.'+ext
    statusBox.textContent='Listo ✅'
  }catch(err){
    statusBox.textContent='❌ '+(err?.message||err)
    console.error(err)
  }finally{
    btnSpeak.disabled=false
  }
}

async function listVoices(){
  voicesOut.classList.remove('hidden'); result.classList.remove('hidden'); statusBox.textContent='Consultando voces...'
  try{
    const res=await fetch('/api/voices')
    if(!res.ok){ const t=await res.text(); throw new Error('Error '+res.status+': '+t)}
    const data=await res.json()
    voicesOut.textContent=JSON.stringify(data,null,2)
    statusBox.textContent='Voces instaladas ✅'
  }catch(err){
    statusBox.textContent='❌ '+(err?.message||err)
    voicesOut.textContent=''
  }
}

form.addEventListener('submit', synthesize)
voicesBtn.addEventListener('click', listVoices)
