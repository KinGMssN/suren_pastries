(() => {
  const form = document.getElementById("cake-request-form");
  if (!form) return;

  const steps = [...form.querySelectorAll(".cake-step")];
  const progressButtons = [...document.querySelectorAll("[data-step-link]")];
  const status = document.getElementById("request-status");
  const imageInput = document.getElementById("reference-image");
  const imagePreview = document.getElementById("reference-preview");
  const previewWrap = document.getElementById("upload-preview");
  const uploadError = document.getElementById("upload-error");
  const addressField = document.getElementById("address-field");
  const addressInput = document.getElementById("delivery-address");
  let currentStep = 1;
  let previewUrl = "";

  function showStep(stepNumber) {
    currentStep = stepNumber;
    steps.forEach((step) => {
      const active = Number(step.dataset.step) === stepNumber;
      step.hidden = !active;
      step.classList.toggle("is-active", active);
    });
    progressButtons.forEach((button) => {
      const number = Number(button.dataset.stepLink);
      button.classList.toggle("is-active", number === stepNumber);
      button.classList.toggle("is-complete", number < stepNumber);
      if (number === stepNumber) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    });
    if (status) status.hidden = true;
    const activeStep = form.querySelector(`[data-step="${stepNumber}"]`);
    activeStep?.querySelector(".step-heading h3")?.focus({ preventScroll: true });
    activeStep?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function selectedValue(name) {
    return form.querySelector(`input[name="${name}"]:checked`)?.value || "";
  }

  function inputValue(name) {
    return form.elements.namedItem(name)?.value.trim() || "";
  }

  function updateConditionalFields() {
    form.querySelectorAll("[data-show-for]").forEach((field) => {
      const [name, value] = field.dataset.showFor.split(":");
      const visible = selectedValue(name) === value;
      field.hidden = !visible;
      const input = field.querySelector("input, textarea");
      if (input) input.required = visible && ["flavour", "size", "shape", "design"].includes(name);
    });

    const deliverySelected = selectedValue("fulfilment") === "Delivery";
    addressField.hidden = !deliverySelected;
    addressInput.required = deliverySelected;
  }

  function customChoice(name, customName) {
    const value = selectedValue(name);
    if (!value) return "";
    if (value.startsWith("Custom")) {
      const custom = inputValue(customName);
      return custom ? `${value.replace("Custom ", "Custom ")}: ${custom}` : value;
    }
    if (value === "Other / Custom") {
      const custom = inputValue(customName);
      return custom ? `${value}: ${custom}` : value;
    }
    return value;
  }

  function updateSummary() {
    const colours = [...form.querySelectorAll('input[name="colours"]:checked')].map((input) => input.value);
    const decorations = [...form.querySelectorAll('input[name="decorations"]:checked')].map((input) => input.value);
    const customColours = inputValue("custom_colours");
    const customDecorations = inputValue("custom_decorations");
    const values = {
      flavour: customChoice("flavour", "custom_flavour"),
      size: customChoice("size", "custom_size"),
      shape: customChoice("shape", "custom_shape"),
      design: customChoice("design", "custom_design"),
      frosting: customChoice("frosting", "custom_frosting"),
      colours: [...colours, customColours].filter(Boolean).join(", "),
      decorations: [...decorations, customDecorations].filter(Boolean).join(", "),
      cake_message: inputValue("cake_message"),
      occasion: inputValue("occasion"),
      fulfilment: selectedValue("fulfilment"),
      required_date: inputValue("required_date"),
      preferred_time: inputValue("preferred_time"),
      delivery_address: selectedValue("fulfilment") === "Delivery" ? inputValue("delivery_address") : "Not applicable",
    };

    Object.entries(values).forEach(([key, value]) => {
      document.querySelectorAll(`[data-summary="${key}"]`).forEach((target) => {
        target.textContent = value || (key === "cake_message" ? "Not added" : "Not selected");
      });
    });
  }

  function setUploadError(message) {
    uploadError.textContent = message;
    imageInput.setCustomValidity(message);
    if (message) imageInput.setAttribute("aria-invalid", "true");
    else imageInput.removeAttribute("aria-invalid");
  }

  function clearPreview(resetInput = true) {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = "";
    if (resetInput) imageInput.value = "";
    imagePreview.removeAttribute("src");
    previewWrap.hidden = true;
    setUploadError("");
  }

  function localDateString() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const day = String(now.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  document.getElementById("required-date").min = localDateString();

  progressButtons.forEach((button) => {
    button.addEventListener("click", () => showStep(Number(button.dataset.stepLink)));
  });
  document.querySelectorAll("[data-show-step]").forEach((link) => {
    link.addEventListener("click", () => showStep(Number(link.dataset.showStep)));
  });
  form.querySelectorAll("[data-next-step]").forEach((button) => {
    button.addEventListener("click", () => showStep(Math.min(currentStep + 1, steps.length)));
  });
  form.querySelectorAll("[data-prev-step]").forEach((button) => {
    button.addEventListener("click", () => showStep(Math.max(currentStep - 1, 1)));
  });
  document.querySelectorAll("[data-edit-step]").forEach((button) => {
    button.addEventListener("click", () => {
      showStep(Number(button.dataset.editStep));
      document.getElementById("cake-builder").scrollIntoView({ behavior: "smooth" });
    });
  });

  form.addEventListener("input", () => {
    updateConditionalFields();
    updateSummary();
  });
  form.addEventListener("change", () => {
    updateConditionalFields();
    updateSummary();
  });

  imageInput.addEventListener("change", () => {
    const file = imageInput.files[0];
    clearPreview(false);
    if (!file) return;

    const allowedTypes = ["image/jpeg", "image/png", "image/webp"];
    const allowedExtensions = [".jpg", ".jpeg", ".png", ".webp"];
    const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!allowedExtensions.includes(extension) || (file.type && !allowedTypes.includes(file.type))) {
      setUploadError("Choose a JPG, PNG, or WEBP image.");
      imageInput.value = "";
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setUploadError("That image is larger than 5 MB. Please choose a smaller file.");
      imageInput.value = "";
      return;
    }

    setUploadError("");
    previewUrl = URL.createObjectURL(file);
    imagePreview.src = previewUrl;
    previewWrap.hidden = false;
  });
  document.getElementById("remove-upload").addEventListener("click", clearPreview);
  function focusFirstInvalid() {
    const invalid = [...form.elements].find((field) => field.willValidate && !field.validity.valid);
    if (!invalid) return false;
    const step = invalid.closest(".cake-step");
    if (step) showStep(Number(step.dataset.step));
    invalid.focus();
    invalid.reportValidity();
    return true;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (focusFirstInvalid()) return;

    updateSummary();
    const requestData = new FormData(form);
    document.dispatchEvent(new CustomEvent("cake-request:ready", {
      detail: { formData: requestData },
    }));

    const phone = document.querySelector(".cake-side-note a")?.textContent.trim();
    status.textContent = `Your details${requestData.get("reference_image")?.name ? " and reference image" : ""} are ready, but this website does not currently have an online cake-request service. Nothing has been sent and your order is not confirmed. Please call ${phone || "the bakery"} or use the WhatsApp enquiry option below to share your request.`;
    status.hidden = false;
    status.focus();
    status.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  updateConditionalFields();
  updateSummary();
})();
