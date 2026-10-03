export function extractJobsFromResponse(responseData) {
  if (!Array.isArray(responseData?.jobs)) {
    throw new Error('Agent jobs reply is not a { jobs } envelope')
  }
  return responseData.jobs
}
