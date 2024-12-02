// app.js

// Immediately Invoked Function Expression (IIFE) to avoid polluting the global scope
(() => {
  // Elements
  const accessButton = document.getElementById('access-protected');
  const invoiceSection = document.getElementById('invoice-section');
  const invoiceQR = document.getElementById('invoice-qr');
  const invoiceText = document.getElementById('invoice-text');
  const paymentStatus = document.getElementById('payment-status');
  const protectedContent = document.getElementById('protected-content');
  const resourceData = document.getElementById('resource-data');
  const message = document.getElementById('message');

  // LSAT Token Storage
  let lsatToken = null;

  // Function to initialize the application
  const init = () => {
    // Check if LSAT token exists in sessionStorage
    lsatToken = sessionStorage.getItem('lsatToken');
    if (lsatToken) {
      // Try accessing the protected resource directly
      accessProtectedResource();
    } else {
      // Show the access button
      accessButton.style.display = 'block';
    }
  };

  // Event listener for the access button
  accessButton.addEventListener('click', () => {
    accessProtectedResource();
  });

  // Function to access the protected resource
  const accessProtectedResource = async () => {
    // Hide previous messages and sections
    message.textContent = '';
    accessButton.style.display = 'none';
    invoiceSection.style.display = 'none';
    protectedContent.style.display = 'none';

    try {
      // Prepare headers
      const headers = {};
      if (lsatToken) {
        headers['Authorization'] = `L402 ${lsatToken}`;
      }

      // Make the request to the protected resource
      const response = await fetch('https://localhost:8000/protected-resource', { headers });

      if (response.status === 200) {
        // Successfully accessed the protected resource
        const data = await response.json();
        resourceData.textContent = data.message;
        protectedContent.style.display = 'block';
      } else if (response.status === 402) {
        // Payment Required - Handle LSAT challenge
        await handleLsatChallenge(response);
      } else {
        // Other errors
        message.textContent = `Error: ${response.status} ${response.statusText}`;
        accessButton.style.display = 'block';
      }
    } catch (error) {
      console.error('Error accessing protected resource:', error);
      message.textContent = 'An error occurred while accessing the protected resource.';
      accessButton.style.display = 'block';
    }
  };

  // Function to handle LSAT challenge
  const handleLsatChallenge = async (response) => {
    // Parse the WWW-Authenticate header
    const wwwAuthenticate = response.headers.get('WWW-Authenticate');
    if (!wwwAuthenticate) {
      message.textContent = 'Authentication failed: WWW-Authenticate header missing.';
      accessButton.style.display = 'block';
      return;
    }

    // Extract macaroon and invoice using a regular expression
    const lsatRegex = /macaroon="([^"]+)", invoice="([^"]+)"/;
    const matches = wwwAuthenticate.match(lsatRegex);
    if (!matches || matches.length !== 3) {
      message.textContent = 'Authentication failed: Invalid WWW-Authenticate header format.';
      accessButton.style.display = 'block';
      return;
    }

    const macaroon = matches[1];
    const invoice = matches[2];

    // Store the macaroon in sessionStorage
    lsatToken = macaroon;
    sessionStorage.setItem('lsatToken', lsatToken);

    // Display the invoice to the user
    displayInvoice(invoice);

    // Optionally, poll for payment confirmation
    pollPaymentConfirmation();
  };

  // Function to display the invoice
  const displayInvoice = (invoice) => {
    // Generate QR code URL
    const qrCodeUrl = `https://api.qrserver.com/v1/create-qr-code/?data=${encodeURIComponent('lightning:' + invoice)}&size=200x200`;
    invoiceQR.src = qrCodeUrl;

    // Display the invoice text
    invoiceText.value = invoice;

    // Show the invoice section
    invoiceSection.style.display = 'block';
  };

  // Function to poll for payment confirmation
  const pollPaymentConfirmation = async () => {
    // Poll the server to check if the payment has been received
    const maxAttempts = 12; // Adjust as needed
    const interval = 5000; // 5 seconds
    let attempts = 0;

    const checkPayment = async () => {
      attempts += 1;
      try {
        // Prepare headers with the LSAT token
        const headers = {
          'Authorization': `L402 ${lsatToken}`
        };

        // Make a request to the protected resource
        const response = await fetch('https://localhost:8000/protected-resource', { headers });

        if (response.status === 200) {
          // Payment confirmed, access granted
          const data = await response.json();
          resourceData.textContent = data.message;
          invoiceSection.style.display = 'none';
          protectedContent.style.display = 'block';
          message.textContent = '';
          return;
        } else if (response.status === 402) {
          // Payment still pending
          if (attempts < maxAttempts) {
            setTimeout(checkPayment, interval);
          } else {
            message.textContent = 'Payment not confirmed within the expected time.';
            invoiceSection.style.display = 'none';
            accessButton.style.display = 'block';
          }
        } else {
          // Other errors
          message.textContent = `Error: ${response.status} ${response.statusText}`;
          accessButton.style.display = 'block';
        }
      } catch (error) {
        console.error('Error checking payment status:', error);
        message.textContent = 'An error occurred while checking payment status.';
        accessButton.style.display = 'block';
      }
    };

    // Start polling
    checkPayment();
  };

  // Initialize the application
  init();
})();

