
"use strict";

document.addEventListener("DOMContentLoaded", () => {

    // 1. Dynamic progress bars
    document.querySelectorAll(".progress-fill[data-percent]").forEach((bar) => {
        const percent = Number(bar.dataset.percent);
        const safePercent = Number.isFinite(percent)
            ? Math.max(0, Math.min(100, percent))
            : 0;

        bar.style.width = `${safePercent}%`;
    });

    // 2. Show / hide password
    document.querySelectorAll("[data-toggle-password]").forEach((button) => {
        button.addEventListener("click", () => {
            const inputId = button.getAttribute("data-toggle-password");
            const input = inputId
                ? document.getElementById(inputId)
                : button.closest(".password-field")?.querySelector("input");

            if (!input) return;

            const showPassword = input.type === "password";
            input.type = showPassword ? "text" : "password";

            button.setAttribute(
                "aria-label",
                showPassword ? "Hide password" : "Show password"
            );

            button.setAttribute("aria-pressed", String(showPassword));

            if (button.dataset.showText) {
                button.textContent = showPassword
                    ? (button.dataset.hideText || "Hide")
                    : button.dataset.showText;
            }
        });
    });

    // 3. Registration password confirmation
    const registerForm = document.querySelector(
        'form[action$="/register"]'
    );

    if (registerForm) {
        const password = registerForm.querySelector(
            'input[name="password"]'
        );

        const confirmPassword = registerForm.querySelector(
            'input[name="confirm_password"]'
        );

        if (password && confirmPassword) {
            const checkPasswords = () => {
                const mismatch =
                    confirmPassword.value !== "" &&
                    password.value !== confirmPassword.value;

                confirmPassword.setCustomValidity(
                    mismatch ? "Passwords do not match." : ""
                );
            };

            password.addEventListener("input", checkPasswords);
            confirmPassword.addEventListener("input", checkPasswords);
        }
    }

    // 4. Set today's date where requested
    const now = new Date();

    const today = [
        now.getFullYear(),
        String(now.getMonth() + 1).padStart(2, "0"),
        String(now.getDate()).padStart(2, "0")
    ].join("-");

    document.querySelectorAll(
        'input[type="date"][data-default-today]'
    ).forEach((input) => {
        if (!input.value) {
            input.value = today;
        }
    });

    // 5. Positive amount validation
    document.querySelectorAll(
        'input[name="amount"], input[data-positive-amount]'
    ).forEach((input) => {
        const validateAmount = () => {
            const value = input.value.trim();
            const amount = Number(value);

            if (
                value !== "" &&
                (!Number.isFinite(amount) || amount <= 0)
            ) {
                input.setCustomValidity(
                    "Please enter an amount greater than zero."
                );
            } else {
                input.setCustomValidity("");
            }
        };

        input.addEventListener("input", validateAmount);
        input.addEventListener("change", validateAmount);
    });

    // 6. Confirm transaction deletion only once
    document.querySelectorAll(
        'form[data-confirm], form[action*="/delete"]'
    ).forEach((form) => {
        // Avoid duplicate confirmation if the form already
        // has an inline onsubmit confirmation.
        if (form.hasAttribute("onsubmit")) return;

        form.addEventListener("submit", (event) => {
            const message = form.dataset.confirm ||
                "Are you sure you want to delete this transaction?";

            if (!window.confirm(message)) {
                event.preventDefault();
            }
        });
    });

    // 7. Dismiss flash messages
    document.querySelectorAll(".flash-dismiss").forEach((button) => {
        button.addEventListener("click", () => {
            const message = button.closest(".flash-message");

            if (message) {
                message.remove();
            }
        });
    });

});
