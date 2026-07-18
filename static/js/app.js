/**
 * ============================================================================
 *  BRAT LYRIC VIDEO GENERATOR — Frontend Application
 *  Handles file uploads, configuration, API calls, polling, and downloads.
 * ============================================================================
 */

(() => {
    'use strict';

    // ── State ──────────────────────────────────────────────────────────
    const state = {
        audioFile: null,
        lyricsFile: null,
        mode: 'both',
        fps: 30,
        fontSize: 90,
        currentJobId: null,
        pollInterval: null,
    };

    // ── DOM References ─────────────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const dom = {
        // Dropzones
        dropzoneAudio:   $('#dropzone-audio'),
        dropzoneLyrics:  $('#dropzone-lyrics'),
        inputAudio:      $('#input-audio'),
        inputLyrics:     $('#input-lyrics'),
        audioFilename:   $('#audio-filename'),
        lyricsFilename:  $('#lyrics-filename'),

        // Config
        modeSelector:    $('#mode-selector'),
        sliderFps:       $('#slider-fps'),
        sliderFontsize:  $('#slider-fontsize'),
        fpsValue:        $('#fps-value'),
        fontsizeValue:   $('#fontsize-value'),
        previewText:     $('#preview-text'),
        previewInput:    $('#preview-input'),
        previewBtn:      $('#preview-btn'),
        previewFrame:    $('#preview-frame'),

        // Generate
        generateBtn:     $('#generate-btn'),
        generateHint:    $('#generate-hint'),
        generateSection: $('#generate-section'),

        // Steps
        stepUpload:      $('#step-upload'),
        stepConfig:      $('#step-config'),
        stepProgress:    $('#step-progress'),
        stepResults:     $('#step-results'),
        stepError:       $('#step-error'),

        // Progress
        progressBar:     $('#progress-bar'),
        progressPercent: $('#progress-percent'),
        progressMessage: $('#progress-message'),
        progressSpinner: $('#progress-spinner'),

        // Results
        resultPreviewImg:  $('#result-preview-img'),
        resultDownloads:   $('#result-downloads'),
        nleInstructions:   $('#nle-instructions'),
        resetBtn:          $('#reset-btn'),
        errorMessage:      $('#error-message'),
        errorResetBtn:     $('#error-reset-btn'),
    };


    // ════════════════════════════════════════════════════════════════════
    //  FILE UPLOAD HANDLING
    // ════════════════════════════════════════════════════════════════════

    function initDropzones() {
        // --- Audio dropzone ---
        setupDropzone(dom.dropzoneAudio, dom.inputAudio, (file) => {
            state.audioFile = file;
            dom.audioFilename.textContent = file.name;
            dom.dropzoneAudio.classList.add('dropzone--has-file');
            updateGenerateButton();
        });

        // --- Lyrics dropzone ---
        setupDropzone(dom.dropzoneLyrics, dom.inputLyrics, (file) => {
            state.lyricsFile = file;
            dom.lyricsFilename.textContent = file.name;
            dom.dropzoneLyrics.classList.add('dropzone--has-file');
            updateGenerateButton();
        });
    }

    function setupDropzone(zone, input, onFile) {
        // Click to open file picker
        zone.addEventListener('click', () => input.click());
        zone.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                input.click();
            }
        });

        // File input change
        input.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                onFile(e.target.files[0]);
            }
        });

        // Drag & drop events
        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('dropzone--dragover');
        });

        zone.addEventListener('dragleave', (e) => {
            e.preventDefault();
            zone.classList.remove('dropzone--dragover');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('dropzone--dragover');
            if (e.dataTransfer.files.length > 0) {
                onFile(e.dataTransfer.files[0]);
            }
        });
    }


    // ════════════════════════════════════════════════════════════════════
    //  CONFIGURATION CONTROLS
    // ════════════════════════════════════════════════════════════════════

    function initConfig() {
        // Mode selector buttons
        dom.modeSelector.addEventListener('click', (e) => {
            const btn = e.target.closest('.mode-btn');
            if (!btn) return;

            $$('.mode-btn').forEach(b => b.classList.remove('mode-btn--active'));
            btn.classList.add('mode-btn--active');
            state.mode = btn.dataset.mode;
        });

        // FPS slider
        dom.sliderFps.addEventListener('input', (e) => {
            state.fps = parseInt(e.target.value);
            dom.fpsValue.textContent = `${state.fps} fps`;
        });

        // Font size slider
        dom.sliderFontsize.addEventListener('input', (e) => {
            state.fontSize = parseInt(e.target.value);
            dom.fontsizeValue.textContent = `${state.fontSize} px`;
            updatePreviewSize();
        });

        // Live text preview
        dom.previewInput.addEventListener('input', (e) => {
            const text = e.target.value.toLowerCase() || 'brat';
            dom.previewText.textContent = text;
        });

        // Server-rendered preview button
        dom.previewBtn.addEventListener('click', fetchServerPreview);
    }

    function updatePreviewSize() {
        // Map font size (40-160) to a CSS rem value for the preview
        const minRem = 1.0;
        const maxRem = 3.5;
        const ratio = (state.fontSize - 40) / (160 - 40);
        const rem = minRem + ratio * (maxRem - minRem);
        dom.previewText.style.fontSize = `${rem}rem`;
    }

    async function fetchServerPreview() {
        dom.previewBtn.textContent = '...';
        dom.previewBtn.disabled = true;

        try {
            const resp = await fetch('/api/preview-lyric', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    text: dom.previewInput.value || 'brat',
                    font_size: state.fontSize,
                }),
            });

            const data = await resp.json();
            if (data.preview_url) {
                // Replace the CSS preview with a server-rendered image
                dom.previewFrame.innerHTML = `<img src="${data.preview_url}" alt="Server preview" style="width:100%;height:100%;object-fit:contain;border-radius:8px;">`;
            }
        } catch (err) {
            console.error('Preview failed:', err);
        } finally {
            dom.previewBtn.textContent = '↻';
            dom.previewBtn.disabled = false;
        }
    }


    // ════════════════════════════════════════════════════════════════════
    //  GENERATE BUTTON
    // ════════════════════════════════════════════════════════════════════

    function updateGenerateButton() {
        const ready = state.audioFile;
        dom.generateBtn.disabled = !ready;
        dom.generateHint.textContent = ready
            ? `ready to generate (${state.mode} mode)`
            : 'upload audio file to start';
    }

    function initGenerate() {
        dom.generateBtn.addEventListener('click', startGeneration);
    }

    async function startGeneration() {
        if (!state.audioFile) return;

        // Build form data
        const formData = new FormData();
        formData.append('audio', state.audioFile);
        if (state.lyricsFile) {
            formData.append('lyrics', state.lyricsFile);
        }
        formData.append('mode', state.mode);
        formData.append('fps', state.fps);
        formData.append('font_size', state.fontSize);

        // Transition to progress view
        showStep('progress');

        try {
            const resp = await fetch('/api/generate', {
                method: 'POST',
                body: formData,
            });

            const data = await resp.json();

            if (!resp.ok) {
                showError(data.error || 'Upload failed.');
                return;
            }

            state.currentJobId = data.job_id;
            startPolling();

        } catch (err) {
            showError(`Network error: ${err.message}`);
        }
    }


    // ════════════════════════════════════════════════════════════════════
    //  STATUS POLLING
    // ════════════════════════════════════════════════════════════════════

    function startPolling() {
        if (state.pollInterval) clearInterval(state.pollInterval);
        state.pollInterval = setInterval(pollStatus, 800);
    }

    function stopPolling() {
        if (state.pollInterval) {
            clearInterval(state.pollInterval);
            state.pollInterval = null;
        }
    }

    async function pollStatus() {
        if (!state.currentJobId) return;

        try {
            const resp = await fetch(`/api/status/${state.currentJobId}`);
            const data = await resp.json();

            // Update progress bar
            updateProgress(data);

            if (data.status === 'done') {
                stopPolling();
                showResults(data);
            } else if (data.status === 'error') {
                stopPolling();
                showError(data.error || 'Unknown error occurred.');
            }
        } catch (err) {
            // Don't stop polling on transient network errors
            console.error('Poll error:', err);
        }
    }

    function updateProgress(data) {
        dom.progressBar.style.width = `${data.progress}%`;
        dom.progressPercent.textContent = `${data.progress}%`;
        dom.progressMessage.textContent = data.message || '...';
    }


    // ════════════════════════════════════════════════════════════════════
    //  RESULTS DISPLAY
    // ════════════════════════════════════════════════════════════════════

    function showResults(data) {
        showStep('results');

        // Set preview image
        if (data.preview_path) {
            dom.resultPreviewImg.src = data.preview_path;
            dom.resultPreviewImg.parentElement.style.display = 'block';
        } else {
            dom.resultPreviewImg.parentElement.style.display = 'none';
        }

        // Build download cards
        dom.resultDownloads.innerHTML = '';
        const outputs = data.outputs || {};

        if (outputs.video) {
            addDownloadCard('🎬', 'mp4 video', 'synced lyric video with audio', 'video');
        }
        if (outputs.nle_zip) {
            addDownloadCard('📦', 'nle asset pack', 'png sequence + fcpxml + edl (.zip)', 'nle_zip');
        }
        if (outputs.fcpxml) {
            addDownloadCard('📋', 'fcpxml timeline', 'for davinci resolve / final cut pro', 'fcpxml');
        }
        if (outputs.edl) {
            addDownloadCard('📝', 'edl timeline', 'cmx3600 for premiere pro', 'edl');
        }

        // Show NLE instructions if NLE outputs exist
        if (outputs.fcpxml || outputs.edl || outputs.nle_zip) {
            dom.nleInstructions.style.display = 'block';
        } else {
            dom.nleInstructions.style.display = 'none';
        }
    }

    function addDownloadCard(icon, title, desc, fileType) {
        const a = document.createElement('a');
        a.href = `/api/download/${state.currentJobId}/${fileType}`;
        a.className = 'download-card fade-in';
        a.innerHTML = `
            <span class="download-card__icon">${icon}</span>
            <div class="download-card__info">
                <div class="download-card__title">${title}</div>
                <div class="download-card__desc">${desc}</div>
            </div>
            <span class="download-card__arrow">↓</span>
        `;
        dom.resultDownloads.appendChild(a);
    }


    // ════════════════════════════════════════════════════════════════════
    //  VIEW MANAGEMENT
    // ════════════════════════════════════════════════════════════════════

    function showStep(step) {
        // Hide/show sections based on the current step
        dom.stepUpload.style.display      = (step === 'upload' || step === 'progress' || step === 'results') ? '' : '';
        dom.stepConfig.style.display      = (step === 'upload' || step === 'progress' || step === 'results') ? '' : '';
        dom.generateSection.style.display = step === 'upload' ? '' : 'none';

        dom.stepProgress.style.display = step === 'progress' ? '' : 'none';
        dom.stepResults.style.display  = step === 'results' ? '' : 'none';
        dom.stepError.style.display    = step === 'error' ? '' : 'none';

        if (step === 'progress') {
            dom.stepUpload.style.display = 'none';
            dom.stepConfig.style.display = 'none';
            dom.stepProgress.classList.add('fade-in');
        }

        if (step === 'results') {
            dom.stepUpload.style.display = 'none';
            dom.stepConfig.style.display = 'none';
            dom.stepResults.classList.add('slide-up');
        }

        if (step === 'error') {
            dom.stepUpload.style.display = 'none';
            dom.stepConfig.style.display = 'none';
            dom.generateSection.style.display = 'none';
        }

        // Scroll to top of relevant section
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function showError(message) {
        showStep('error');
        dom.errorMessage.textContent = message;
    }

    function resetApp() {
        stopPolling();
        state.currentJobId = null;

        // Reset file states
        state.audioFile = null;
        state.lyricsFile = null;
        dom.inputAudio.value = '';
        dom.inputLyrics.value = '';
        dom.audioFilename.textContent = '';
        dom.lyricsFilename.textContent = '';
        dom.dropzoneAudio.classList.remove('dropzone--has-file');
        dom.dropzoneLyrics.classList.remove('dropzone--has-file');

        // Reset progress
        dom.progressBar.style.width = '0%';
        dom.progressPercent.textContent = '0%';
        dom.progressMessage.textContent = 'starting...';

        // Reset preview frame to CSS preview
        dom.previewFrame.innerHTML = `<div class="preview-text" id="preview-text">brat</div>`;
        // Re-reference since we replaced innerHTML
        // Re-bind is handled by using dom lookup in updatePreviewSize

        updateGenerateButton();

        // Show upload/config steps
        dom.stepUpload.style.display = '';
        dom.stepConfig.style.display = '';
        dom.generateSection.style.display = '';
        dom.stepProgress.style.display = 'none';
        dom.stepResults.style.display = 'none';
        dom.stepError.style.display = 'none';

        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function initReset() {
        dom.resetBtn.addEventListener('click', resetApp);
        dom.errorResetBtn.addEventListener('click', resetApp);
    }


    // ════════════════════════════════════════════════════════════════════
    //  INITIALIZATION
    // ════════════════════════════════════════════════════════════════════

    function init() {
        initDropzones();
        initConfig();
        initGenerate();
        initReset();
        updateGenerateButton();

        // Animate steps in on load
        const steps = $$('.step');
        steps.forEach((step, i) => {
            step.style.animationDelay = `${i * 0.15}s`;
        });
    }

    // Wait for DOM, then go
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
