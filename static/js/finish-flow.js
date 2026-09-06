(function initFinishFlow(global) {
    'use strict';

    function defaultSoundEnabled() {
        return true;
    }

    function normalizeRewardValue(value) {
        const parsed = Number.parseInt(String(value), 10);
        if (Number.isNaN(parsed)) return 0;
        return Math.max(0, parsed);
    }

    function createStandaloneAudioContext() {
        const AudioCtx = global.AudioContext || global.webkitAudioContext;
        if (!AudioCtx) return null;
        try {
            return new AudioCtx();
        } catch (err) {
            return null;
        }
    }

    function createFinishFlow(config) {
        const cfg = config || {};
        const showClasses = Array.isArray(cfg.showClasses) && cfg.showClasses.length
            ? cfg.showClasses.slice()
            : ['show'];

        const gameOverEl = cfg.gameOverEl || null;
        const summaryContentEl = cfg.summaryContentEl || null;
        const rewardScreenEl = cfg.rewardScreenEl || null;
        const rewardScreenNeuronsEl = cfg.rewardScreenNeuronsEl || null;
        const rewardScreenUnitIconEl = cfg.rewardScreenUnitIconEl || null;
        const bannerMessageEl = cfg.bannerMessageEl || null;
        const scoreDetailsEl = cfg.scoreDetailsEl || null;
        const bannerActionsEl = cfg.bannerActionsEl || null;
        const finalScoreEl = cfg.finalScoreEl || null;
        const continueBtnEl = cfg.continueBtnEl || null;
        const rewardContinueBtnEl = cfg.rewardContinueBtnEl || null;

        const continueButtonText = cfg.continueButtonText || 'Next';
        const rewardContinueButtonText = cfg.rewardContinueButtonText || 'Continue';
        const openingRewardText = cfg.openingRewardText || 'Opening rewards...';
        const continuingText = cfg.continuingText || 'Continuing...';
        const runCompletedText = cfg.runCompletedText || 'Run completed';
        const redirectUrl = cfg.redirectUrl || null;

        const revealDelayMs = Number.isFinite(cfg.revealDelayMs) ? cfg.revealDelayMs : 750;
        const scoreDelayMs = Number.isFinite(cfg.scoreDelayMs) ? cfg.scoreDelayMs : 1750;
        const actionsDelayMs = Number.isFinite(cfg.actionsDelayMs) ? cfg.actionsDelayMs : 2050;
        const rewardVolumeBoost = Number.isFinite(cfg.rewardVolumeBoost) ? cfg.rewardVolumeBoost : 2.5;

        const getSoundEnabled = typeof cfg.getSoundEnabled === 'function'
            ? cfg.getSoundEnabled
            : defaultSoundEnabled;
        const ensureAudioContext = typeof cfg.ensureAudioContext === 'function'
            ? cfg.ensureAudioContext
            : null;

        let isRewardActive = false;
        let rewardAudioCtx = null;
        let timers = [];

        function clearTimers() {
            if (!timers.length) return;
            timers.forEach((timerId) => global.clearTimeout(timerId));
            timers = [];
        }

        function schedule(callback, delayMs) {
            const timerId = global.setTimeout(callback, delayMs);
            timers.push(timerId);
            return timerId;
        }

        function isSoundEnabled() {
            try {
                return Boolean(getSoundEnabled());
            } catch (err) {
                return true;
            }
        }

        function getRewardAudioContext() {
            if (!isSoundEnabled()) return null;
            if (!rewardAudioCtx) {
                rewardAudioCtx = ensureAudioContext ? (ensureAudioContext() || null) : null;
                if (!rewardAudioCtx) {
                    rewardAudioCtx = createStandaloneAudioContext();
                }
            }
            if (rewardAudioCtx && rewardAudioCtx.state === 'suspended' && typeof rewardAudioCtx.resume === 'function') {
                rewardAudioCtx.resume().catch(() => {});
            }
            return rewardAudioCtx;
        }

        function playRunCompleteReward() {
            const audioCtx = getRewardAudioContext();
            if (!audioCtx) return;

            const now = audioCtx.currentTime + 0.01;
            const master = audioCtx.createGain();
            master.gain.setValueAtTime(0.0001, now);
            master.gain.exponentialRampToValueAtTime(0.21 * rewardVolumeBoost, now + 0.04);
            master.gain.exponentialRampToValueAtTime(0.0001, now + 1.05);
            master.connect(audioCtx.destination);

            const jingle = [
                { freq: 523.25, t: 0.0, dur: 0.18, gain: 0.11 },
                { freq: 659.25, t: 0.1, dur: 0.2, gain: 0.12 },
                { freq: 783.99, t: 0.2, dur: 0.22, gain: 0.13 },
                { freq: 1046.5, t: 0.34, dur: 0.34, gain: 0.16 },
                { freq: 1318.5, t: 0.54, dur: 0.36, gain: 0.14 },
            ];

            jingle.forEach(({ freq, t, dur, gain }) => {
                const start = now + t;
                const body = audioCtx.createOscillator();
                const bodyGain = audioCtx.createGain();
                body.type = 'triangle';
                body.frequency.setValueAtTime(freq, start);
                body.frequency.exponentialRampToValueAtTime(freq * 1.06, start + dur);
                bodyGain.gain.setValueAtTime(0.0001, start);
                bodyGain.gain.exponentialRampToValueAtTime(gain * rewardVolumeBoost, start + 0.02);
                bodyGain.gain.exponentialRampToValueAtTime(0.0001, start + dur);
                body.connect(bodyGain);
                bodyGain.connect(master);
                body.start(start);
                body.stop(start + dur + 0.02);

                const sparkle = audioCtx.createOscillator();
                const sparkleGain = audioCtx.createGain();
                sparkle.type = 'sine';
                sparkle.frequency.setValueAtTime(freq * 2, start + 0.01);
                sparkle.frequency.exponentialRampToValueAtTime(freq * 2.3, start + Math.min(0.12, dur));
                sparkleGain.gain.setValueAtTime(0.0001, start + 0.01);
                sparkleGain.gain.exponentialRampToValueAtTime((gain * 0.42) * rewardVolumeBoost, start + 0.03);
                sparkleGain.gain.exponentialRampToValueAtTime(0.0001, start + Math.min(0.14, dur));
                sparkle.connect(sparkleGain);
                sparkleGain.connect(master);
                sparkle.start(start + 0.01);
                sparkle.stop(start + Math.min(0.16, dur + 0.02));
            });
        }

        function renderRewardUnitIcon() {
            if (!rewardScreenUnitIconEl) return;
            const tmpl = global.document.getElementById('neuronSvgTemplate');
            rewardScreenUnitIconEl.innerHTML = tmpl ? tmpl.innerHTML : '';
        }

        function reset(options) {
            const opts = options || {};
            clearTimers();
            isRewardActive = false;

            const classesToRemove = Array.isArray(opts.removeShowClasses) && opts.removeShowClasses.length
                ? opts.removeShowClasses
                : showClasses;
            if (gameOverEl) {
                classesToRemove.forEach((className) => {
                    if (className) {
                        gameOverEl.classList.remove(className);
                    }
                });
            }

            if (summaryContentEl) {
                summaryContentEl.classList.remove('choreo-hidden', 'choreo-visible', 'choreo-visible-flex');
                summaryContentEl.style.display = 'flex';
            }
            if (rewardScreenEl) {
                rewardScreenEl.className = 'reward-screen choreo-hidden';
            }
            if (rewardScreenNeuronsEl) {
                rewardScreenNeuronsEl.textContent = '0';
            }
            if (bannerMessageEl) {
                bannerMessageEl.className = 'banner-message choreo-hidden';
                bannerMessageEl.textContent = opts.runCompletedText || runCompletedText;
            }
            if (scoreDetailsEl) {
                scoreDetailsEl.className = 'score-details choreo-hidden';
            }
            if (bannerActionsEl) {
                bannerActionsEl.className = 'banner-actions choreo-hidden';
            }
            if (continueBtnEl) {
                continueBtnEl.disabled = false;
                continueBtnEl.textContent = continueButtonText;
            }
            if (rewardContinueBtnEl) {
                rewardContinueBtnEl.disabled = false;
                rewardContinueBtnEl.textContent = rewardContinueButtonText;
            }
            renderRewardUnitIcon();

            if (typeof opts.onReset === 'function') {
                opts.onReset();
            }
        }

        function showSummary(finalScore, options) {
            const opts = options || {};
            clearTimers();

            if (typeof opts.onBeforePrepare === 'function') {
                opts.onBeforePrepare();
            }

            if (summaryContentEl) {
                summaryContentEl.classList.remove('choreo-hidden');
                summaryContentEl.style.display = 'flex';
            }
            if (rewardScreenEl) {
                rewardScreenEl.className = 'reward-screen choreo-hidden';
            }
            if (bannerMessageEl) {
                bannerMessageEl.className = 'banner-message choreo-hidden';
                bannerMessageEl.textContent = opts.runCompletedText || runCompletedText;
            }
            if (scoreDetailsEl) {
                scoreDetailsEl.className = 'score-details choreo-hidden';
            }
            if (bannerActionsEl) {
                bannerActionsEl.className = 'banner-actions choreo-hidden';
            }
            if (finalScoreEl) {
                finalScoreEl.textContent = String(finalScore);
            }

            const classesToAdd = Array.isArray(opts.showClasses) && opts.showClasses.length
                ? opts.showClasses
                : showClasses;
            if (gameOverEl) {
                classesToAdd.forEach((className) => {
                    if (className) {
                        gameOverEl.classList.add(className);
                    }
                });
            }

            if (typeof opts.onPrepared === 'function') {
                opts.onPrepared();
            }

            schedule(() => {
                if (bannerMessageEl) {
                    bannerMessageEl.classList.remove('choreo-hidden');
                    bannerMessageEl.classList.add('banner-message-visible', 'banner-message-reward');
                }
                playRunCompleteReward();
                if (typeof opts.onMessageReveal === 'function') {
                    opts.onMessageReveal();
                }
            }, Number.isFinite(opts.revealDelayMs) ? opts.revealDelayMs : revealDelayMs);

            schedule(() => {
                if (scoreDetailsEl) {
                    scoreDetailsEl.classList.remove('choreo-hidden');
                    scoreDetailsEl.classList.add('choreo-visible');
                }
                if (typeof opts.onScoreReveal === 'function') {
                    opts.onScoreReveal();
                }
            }, Number.isFinite(opts.scoreDelayMs) ? opts.scoreDelayMs : scoreDelayMs);

            schedule(() => {
                if (bannerActionsEl) {
                    bannerActionsEl.classList.remove('choreo-hidden');
                    bannerActionsEl.classList.add('choreo-visible-flex');
                }
                if (typeof opts.onActionsReveal === 'function') {
                    opts.onActionsReveal();
                }
            }, Number.isFinite(opts.actionsDelayMs) ? opts.actionsDelayMs : actionsDelayMs);
        }

        function showReward(rewardValue, options) {
            const opts = options || {};
            if (isRewardActive) return false;
            isRewardActive = true;

            if (!summaryContentEl || !rewardScreenEl || !rewardScreenNeuronsEl) {
                const fallbackUrl = opts.redirectUrl || redirectUrl;
                if (fallbackUrl) {
                    global.location.href = fallbackUrl;
                }
                return false;
            }

            if (continueBtnEl) {
                continueBtnEl.disabled = true;
                continueBtnEl.textContent = openingRewardText;
            }
            if (rewardContinueBtnEl) {
                rewardContinueBtnEl.disabled = false;
                rewardContinueBtnEl.textContent = rewardContinueButtonText;
            }

            rewardScreenNeuronsEl.textContent = String(normalizeRewardValue(rewardValue));
            summaryContentEl.classList.add('choreo-hidden');
            rewardScreenEl.className = 'reward-screen choreo-visible-flex';
            playRunCompleteReward();

            if (typeof opts.onShown === 'function') {
                opts.onShown();
            }
            return true;
        }

        function continueFromReward(options) {
            const opts = options || {};
            if (rewardContinueBtnEl) {
                rewardContinueBtnEl.disabled = true;
                rewardContinueBtnEl.textContent = continuingText;
            }
            if (typeof opts.onContinue === 'function') {
                opts.onContinue();
                return;
            }
            const target = opts.redirectUrl || redirectUrl;
            if (target) {
                global.location.href = target;
            }
        }

        renderRewardUnitIcon();

        return {
            reset,
            showSummary,
            showReward,
            continueFromReward,
            clearTimers,
            schedule,
            playRunCompleteReward,
            renderRewardUnitIcon,
            normalizeRewardValue,
        };
    }

    global.createFinishFlow = createFinishFlow;
})(window);
